import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import Request
from nicegui import Client, app, ui

from services.device_registry import active_device_options, ensure_active_devices
from services.main_window import register_main_window
from shared.formatters import device_display_name
from shared.styles import add_styles
from storage.measurements_store import graph_latest_row, graph_rows_all, graph_rows_history


MAX_BARS = 24
INITIAL_FETCH_LIMIT = 5000
SAMPLE_BASE_MIN = 5
REALTIME_RETRY_SECONDS = 30.0
REALTIME_PRECHECK_SECONDS = 10.0
REALTIME_POLL_SECONDS = 15.0
REALTIME_POLL_WINDOW_SECONDS = 120.0
REALTIME_IDLE_RETRY_SECONDS = 60.0
REALTIME_MAX_WAIT_SECONDS = 360.0
MENU = [
    ('5 min', 5),
    ('15 min', 15),
    ('30 min', 30),
    ('1 hr', 60),
    ('2 hr', 120),
    ('4 hr', 240),
]

HISTORY_MENU = [
    ('5 min', 5),
    ('15 min', 15),
    ('30 min', 30),
    ('1 hr', 60),
    ('2 hr', 120),
    ('6 hr', 360),
    ('12 hr', 720),
    ('24 hr', 1440),
]


@dataclass(frozen=True)
class ChartSpec:
    key: str
    title: str
    unit: str
    color: str
    coverage: float = 0.90
    round_values: bool = False
    realtime_y_max: float | None = None
    realtime_y_cap: float | None = None

    @property
    def y_title(self) -> str:
        return f'{self.title} {self.unit}' if self.unit.startswith(('(', 'µ')) else f'{self.title} ({self.unit})'


PARTICLE_CHARTS = [
    ChartSpec('pm1p0', 'PM1.0', 'µg/m³', '#ff0000'),
    ChartSpec('pm2p5', 'PM2.5', 'µg/m³', '#bfa600'),
    ChartSpec('pm4p0', 'PM4.0', 'µg/m³', '#00bfbf'),
    ChartSpec('pm10p0', 'PM10.0', 'µg/m³', '#bf00ff'),
]

VOC_NOX_CHARTS = [
    ChartSpec('voc', 'VOC', 'Index', '#ff8000', realtime_y_cap=500),
    ChartSpec('nox', 'NOx', 'Index', '#00ff00'),
]

AMBIENT_CHARTS = [
    ChartSpec('co2', 'CO2', 'ppm', '#990000', coverage=0.85, round_values=True),
    ChartSpec('temp', 'Temperatura', '°C', '#006600', coverage=0.85),
    ChartSpec('hum', 'Humedad relativa', '%', '#0000cc', coverage=0.85, round_values=True),
]


def _nav() -> None:
    with ui.element('nav').classes('top-nav'):
        ui.link('Inicio', '/dashboard')
        ui.label('|')
        ui.link('Gráficas Partículas', '/graficas/particulas')
        ui.label('|')
        ui.link('Gráficas VOC & NOx', '/graficas/voc-nox')
        ui.label('|')
        ui.link('Gráficas del Historial', '/graficas/historial')
        ui.label('|')
        ui.link('Ubicaciones', '/ubicaciones')
        ui.label('|')
        ui.link('Gráficas CO2, Temperatura & Humedad', '/graficas/ambientales')
        ui.label('|')


def _add_graph_styles() -> None:
    ui.add_head_html(
        '''
        <style>
        .chart-card {
            width: 100%;
            max-width: 1200px;
            margin: 30px auto;
            background: #cce5dc;
            border-radius: 10px;
            padding: 20px;
            box-sizing: border-box;
        }
        .history-chart-card {
            height: 660px;
            max-height: 660px;
            overflow: hidden;
        }
        .history-chart-card .js-plotly-plot,
        .history-chart-card .plot-container,
        .history-chart-card .svg-container {
            height: 620px !important;
            max-height: 620px !important;
        }
        .agg-toolbar-wrap {
            display: flex;
            flex-direction: column;
            gap: 6px;
            margin: 8px 0 4px 0;
            width: 100%;
        }
        .agg-chart-title {
            font-weight: bold;
            font-size: 20px;
            font-family: Arial, sans-serif;
            color: #000;
            text-align: center;
            line-height: 1.1;
        }
        .agg-toolbar-label {
            font-weight: bold;
            font-size: 16px;
            font-family: Arial, sans-serif;
            color: #000;
            text-align: left;
        }
        .agg-toolbar {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            align-items: center;
            justify-content: flex-start;
        }
        .agg-btn {
            cursor: pointer;
            user-select: none;
            padding: 6px 10px;
            border-radius: 10px;
            background: #e9f4ef !important;
            border: 2px solid #2a2a2a !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            font-family: Arial, sans-serif !important;
            color: #000 !important;
            width: 96px;
            text-align: center;
            min-height: unset !important;
            transition: transform 0.12s ease, box-shadow 0.12s ease, font-size 0.12s ease;
        }
        .agg-btn:hover { box-shadow: 0 1px 0 rgba(0,0,0,.35); }
        .agg-btn.active {
            transform: scale(1.25);
            font-weight: bold !important;
            font-size: 18px !important;
            background: #d9efe7 !important;
            z-index: 1;
        }
        .history-controls {
            background-color: #cce5dc;
            padding: 20px;
            margin: 20px auto;
            border-radius: 8px;
            max-width: 800px;
            text-align: center;
        }
        .history-select-label {
            margin-bottom: 8px;
            display: block;
            color: #000;
            font-size: 22px;
            font-weight: bold;
            text-align: center;
        }
        .history-slider-box {
            width: 100%;
            max-width: 900px;
            margin: 10px auto 8px auto;
            padding: 8px 4px 18px 4px;
            box-sizing: border-box;
        }
        .history-range-label {
            font-weight: bold;
            font-size: 16px;
            font-family: Arial, sans-serif;
            color: #000;
            text-align: left;
            margin-bottom: 10px;
        }
        .data-table-container {
            width: 100%;
            max-height: 760px;
            overflow: auto;
            margin-top: 24px;
        }
        .data-table-container table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
        }
        .data-table-container thead th {
            position: sticky;
            top: 0;
            z-index: 2;
        }
        .data-table-container th,
        .data-table-container td {
            font-size: 20px;
            text-align: center;
            border: 1px solid black;
            border-radius: 10px;
            padding: 8px;
        }
        .data-table-container th { background-color: #80ffd4; }

        @media (max-width: 900px) {
            .dashboard {
                width: 100%;
                padding: 18px 8px 34px !important;
                overflow-x: hidden;
            }
            .top-nav {
                gap: 6px 8px !important;
                font-size: 15px !important;
                line-height: 1.25;
            }
            .brand-title { font-size: 24px !important; }
            .section-title { font-size: 21px !important; }
            .chart-card {
                width: calc(100vw - 16px);
                max-width: calc(100vw - 16px);
                margin: 18px auto;
                padding: 12px;
                overflow-x: auto;
                overflow-y: hidden;
                -webkit-overflow-scrolling: touch;
            }
            .chart-card .js-plotly-plot,
            .chart-card .plot-container,
            .chart-card .svg-container {
                min-width: 760px !important;
            }
            .history-chart-card {
                height: 620px;
                max-height: 620px;
            }
            .history-chart-card .js-plotly-plot,
            .history-chart-card .plot-container,
            .history-chart-card .svg-container {
                height: 580px !important;
                max-height: 580px !important;
            }
            .agg-toolbar {
                justify-content: center;
                gap: 8px;
            }
            .agg-toolbar-label,
            .history-range-label {
                text-align: center;
            }
            .agg-btn {
                width: 82px;
                padding: 7px 8px;
                font-size: 12px !important;
            }
            .agg-btn.active {
                transform: scale(1.10);
                font-size: 15px !important;
            }
            .history-controls {
                width: calc(100vw - 24px);
                max-width: calc(100vw - 24px);
                padding: 12px;
            }
            .history-select-label { font-size: 18px; }
            .data-table-container {
                max-width: calc(100vw - 16px);
                overflow-x: auto;
            }
            .data-table-container th,
            .data-table-container td {
                font-size: 15px;
                padding: 6px;
                white-space: nowrap;
            }
        }

        @media (max-width: 600px) {
            .dashboard {
                padding: 14px 6px 28px !important;
            }
            .top-nav {
                font-size: 13px !important;
            }
            .brand-title { font-size: 22px !important; }
            .section-title { font-size: 19px !important; }
            .connect-logo {
                width: 78px !important;
                height: 78px !important;
            }
            .chart-card {
                width: calc(100vw - 10px);
                max-width: calc(100vw - 10px);
                padding: 8px;
            }
            .chart-card .js-plotly-plot,
            .chart-card .plot-container,
            .chart-card .svg-container {
                min-width: 720px !important;
            }
            .agg-chart-title { font-size: 17px; }
            .agg-toolbar-label,
            .history-range-label {
                font-size: 14px;
            }
            .agg-btn {
                width: 72px;
                font-size: 11px !important;
            }
            .history-chart-card {
                height: 560px;
                max-height: 560px;
            }
            .history-chart-card .js-plotly-plot,
            .history-chart-card .plot-container,
            .history-chart-card .svg-container {
                height: 520px !important;
                max-height: 520px !important;
            }
        }
        </style>
        '''
    )


def _parse_row_datetime(row: dict[str, Any]) -> datetime | None:
    fecha = str(row.get('fecha') or '').strip()
    hora = str(row.get('hora') or '').strip() or '00:00:00'
    if not fecha:
        return None

    fecha = fecha.replace('/', '-').replace('.', '-')
    parts = fecha.split('-')
    if len(parts) == 3 and len(parts[0]) != 4:
        fecha = f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
    elif len(parts) == 3:
        fecha = f'{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}'

    hora = hora.rstrip('Z').split('+', 1)[0]
    if len(hora) == 5:
        hora = f'{hora}:00'

    try:
        return datetime.fromisoformat(f'{fecha}T{hora[:8]}')
    except ValueError:
        return None


def _rows_to_frame(rows: list[dict[str, Any]]) -> Any:
    import pandas as pd

    prepared: list[dict[str, Any]] = []
    for row in rows:
        dt = _parse_row_datetime(row)
        if dt is None:
            continue
        item = dict(row)
        item['_dt'] = pd.Timestamp(dt)
        prepared.append(item)

    frame = pd.DataFrame(prepared)
    if frame.empty:
        return frame
    return frame.sort_values('_dt')


def _fmt_label(ts: Any) -> str:
    return ts.strftime('%Y-%m-%d %H:%M')


def _short_date_label(date_part: str) -> str:
    parts = date_part.split('-')
    if len(parts) == 3:
        return f'{parts[2]}/{parts[1]}/{parts[0][-2:]}'
    return date_part


def _tick_text(labels: list[str], minutes: int) -> list[str]:
    out: list[str] = []
    last_date = ''
    for label in labels:
        if not label:
            out.append('')
            continue
        date_part, time_part = label.split(' ', 1)
        display = time_part[:5]
        if date_part != last_date:
            display = f'{_short_date_label(date_part)}-{display}'
            last_date = date_part
        out.append(display)
    return out


def _series_data(frame: Any, spec: ChartSpec, minutes: int) -> tuple[list[str], list[float | None]]:
    import pandas as pd

    empty = ([''] * MAX_BARS, [None] * MAX_BARS)
    if frame.empty or spec.key not in frame:
        return empty

    df = frame[['_dt', spec.key]].copy()
    df[spec.key] = pd.to_numeric(df[spec.key], errors='coerce')
    df = df.dropna(subset=[spec.key])
    if df.empty:
        return empty

    if minutes == SAMPLE_BASE_MIN:
        take = df.tail(MAX_BARS)
        labels = [_fmt_label(ts) for ts in take['_dt']]
        values = [float(v) for v in take[spec.key]]
    else:
        width = pd.Timedelta(minutes=minutes)
        last_ts = df['_dt'].max()
        df['_bin'] = df['_dt'].dt.floor(f'{minutes}min')
        grouped = df.groupby('_bin')[spec.key].agg(['mean', 'count']).reset_index()
        grouped = grouped[(grouped['_bin'] + width) <= last_ts]
        required = max(1, math.ceil((minutes / SAMPLE_BASE_MIN) * spec.coverage))
        grouped = grouped[grouped['count'] >= required]
        take = grouped.tail(MAX_BARS)
        labels = [_fmt_label(ts) for ts in take['_bin']]
        values = [float(v) for v in take['mean']]

    if spec.round_values:
        values = [round(v) if v is not None else None for v in values]

    if len(labels) > MAX_BARS:
        labels = labels[-MAX_BARS:]
        values = values[-MAX_BARS:]

    while len(labels) < MAX_BARS:
        labels.append('')
    while len(values) < MAX_BARS:
        values.append(None)

    return labels, values


def _seconds_until_next_realtime_refresh(frame: Any | None) -> float:
    """Calcula cuándo revisar si llegó una nueva medición de tiempo real.

    Estrategia:
    - esperar hasta última medición + SAMPLE_BASE_MIN minutos - 10 s;
    - desde ahí abrir una ventana de 2 min consultando cada 15 s;
    - si no aparece medición nueva en esa ventana, bajar a un retry liviano.
    """
    if frame is None or getattr(frame, 'empty', True) or '_dt' not in frame:
        return REALTIME_RETRY_SECONDS

    try:
        last_dt = frame['_dt'].max()
        if hasattr(last_dt, 'to_pydatetime'):
            last_dt = last_dt.to_pydatetime()
        if getattr(last_dt, 'tzinfo', None) is not None:
            last_dt = last_dt.replace(tzinfo=None)
        probe_start = last_dt + timedelta(minutes=SAMPLE_BASE_MIN, seconds=-REALTIME_PRECHECK_SECONDS)
        probe_end = probe_start + timedelta(seconds=REALTIME_POLL_WINDOW_SECONDS)
        now = datetime.now()
    except Exception:
        return REALTIME_RETRY_SECONDS

    if now < probe_start:
        delay = (probe_start - now).total_seconds()
        return min(max(delay, REALTIME_RETRY_SECONDS), REALTIME_MAX_WAIT_SECONDS)
    if now <= probe_end:
        return REALTIME_POLL_SECONDS
    return REALTIME_IDLE_RETRY_SECONDS


def _build_figure(frame: Any, spec: ChartSpec, minutes: int) -> Any:
    import plotly.graph_objects as go

    labels, values = _series_data(frame, spec, minutes)
    finite = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]
    upper = spec.realtime_y_max if spec.realtime_y_max is not None else (max(finite) * 2 if finite and max(finite) > 0 else 1)
    if spec.realtime_y_cap is not None:
        upper = min(upper, spec.realtime_y_cap)
    x_values = list(range(MAX_BARS))

    fig = go.Figure(
        data=[
            go.Bar(
                x=x_values,
                y=values,
                name=spec.y_title,
                marker={'color': spec.color},
            )
        ]
    )
    fig.update_layout(
        height=600,
        margin={'t': 20, 'l': 60, 'r': 40, 'b': 135},
        bargap=0.2,
        paper_bgcolor='#cce5dc',
        plot_bgcolor='#cce5dc',
        showlegend=False,
        font={'family': 'Arial', 'color': 'black'},
    )
    fig.update_xaxes(
        type='category',
        tickmode='array',
        tickvals=x_values,
        ticktext=_tick_text(labels, minutes),
        tickangle=-45,
        automargin=True,
        gridcolor='black',
        linecolor='black',
        title={'text': '<b>Fecha y Hora de Medición</b>', 'font': {'size': 16, 'color': 'black', 'family': 'Arial'}, 'standoff': 42},
        tickfont={'color': 'black', 'size': 13, 'family': 'Arial'},
    )
    fig.update_yaxes(
        title={'text': f'<b>{spec.y_title}</b>', 'font': {'size': 16, 'color': 'black', 'family': 'Arial'}},
        tickfont={'color': 'black', 'size': 14, 'family': 'Arial'},
        rangemode='tozero',
        gridcolor='black',
        linecolor='black',
        range=[0, upper],
        fixedrange=False,
    )
    return fig


async def _load_frame(device_id: str | None, limit: int = INITIAL_FETCH_LIMIT) -> tuple[Any | None, str | None]:
    try:
        # Las gráficas en tiempo real solo leen SQLite. La sincronización con los ESP32
        # corre en background_sync_loop para evitar bloquear o cortar clientes NiceGUI.
        rows = await asyncio.to_thread(graph_rows_history, limit, device_id)
        return _rows_to_frame(rows), None
    except ModuleNotFoundError as exc:
        missing = exc.name or 'plotly/pandas'
        return None, f'Falta instalar el paquete Python: {missing}'
    except Exception as exc:
        return None, f'No se pudieron cargar las mediciones: {exc}'


def _graph_page(page_title: str, charts: list[ChartSpec]) -> None:
    ui.page_title(page_title)
    add_styles()
    _add_graph_styles()

    states = {spec.key: SAMPLE_BASE_MIN for spec in charts}
    plot_widgets: dict[str, Any] = {}
    buttons: dict[str, list[Any]] = {spec.key: [] for spec in charts}
    frame_cache: Any | None = None
    selected_device_id: str | None = None
    last_realtime_signature: tuple[Any, ...] | None = None
    refresh_running = False

    with ui.element('div').classes('dashboard'):
        _nav()
        with ui.element('div').classes('brand-header'):
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
            ui.label('EcoSensor®').classes('brand-name')
        ui.label(page_title).classes('section-title')
        id_label = ui.label('ID: -').classes('section-title')
        status = ui.label('Cargando gráficas...').classes('status-line mt-3')

        for spec in charts:
            with ui.column().classes('chart-card'):
                ui.label(spec.y_title).classes('agg-chart-title')
                ui.label('Seleccione el intervalo de lecturas').classes('agg-toolbar-label')
                with ui.row().classes('agg-toolbar'):
                    for label, minutes in MENU:
                        button = ui.button(label).props('flat no-caps').classes('agg-btn')
                        buttons[spec.key].append(button)

                        async def select_interval(m: int = minutes, s: ChartSpec = spec) -> None:
                            states[s.key] = m
                            await redraw_one(s)

                        button.on('click', select_interval)
                plot_widgets[spec.key] = ui.plotly({}).classes('w-full')

    def update_active_buttons(spec: ChartSpec) -> None:
        active_minutes = states[spec.key]
        for button, (_, minutes) in zip(buttons[spec.key], MENU):
            if minutes == active_minutes:
                button.classes(add='active')
            else:
                button.classes(remove='active')

    async def redraw_one(spec: ChartSpec) -> None:
        if frame_cache is None:
            return
        try:
            figure = _build_figure(frame_cache, spec, states[spec.key])
            plot_widgets[spec.key].figure = figure
            plot_widgets[spec.key].update()
            update_active_buttons(spec)
        except ModuleNotFoundError as exc:
            status.set_text(f'Falta instalar el paquete Python: {exc.name or "plotly/pandas"}')
        except Exception as exc:
            status.set_text(f'No se pudo generar {spec.y_title}: {exc}')

    async def refresh_sensor_options() -> None:
        nonlocal selected_device_id
        await ensure_active_devices()
        options = active_device_options()
        stored_device_id = str(app.storage.user.get('selected_device_id') or '') or None
        if stored_device_id in options:
            selected_device_id = stored_device_id
        elif selected_device_id not in options:
            selected_device_id = next(iter(options)) if options else None
            if selected_device_id:
                app.storage.user['selected_device_id'] = selected_device_id
            else:
                app.storage.user.pop('selected_device_id', None)
        id_label.set_text(f'ID: {device_display_name(selected_device_id) if selected_device_id else "-"}')

    page_client = ui.context.client

    def client_alive() -> bool:
        return not getattr(page_client, '_deleted', False)

    def schedule_next_refresh(delay_seconds: float) -> None:
        if client_alive():
            ui.timer(delay_seconds, refresh, once=True)

    async def refresh() -> None:
        nonlocal frame_cache, last_realtime_signature, refresh_running
        if not client_alive() or refresh_running:
            return
        refresh_running = True
        next_delay = REALTIME_RETRY_SECONDS
        try:
            await refresh_sensor_options()
            if not selected_device_id:
                status.set_text('No hay EcoSensor activos disponibles.')
                last_realtime_signature = None
                return

            latest = await asyncio.to_thread(graph_latest_row, selected_device_id)
            realtime_signature = (
                selected_device_id,
                (latest or {}).get('_row_id'),
                (latest or {}).get('fecha'),
                (latest or {}).get('hora'),
            )
            if frame_cache is not None and realtime_signature == last_realtime_signature:
                status.set_text('')
                next_delay = _seconds_until_next_realtime_refresh(frame_cache)
                return

            frame, error = await _load_frame(selected_device_id)
            if error:
                status.set_text(error)
                return
            frame_cache = frame
            last_realtime_signature = realtime_signature
            status.set_text('')
            for spec in charts:
                await redraw_one(spec)
            next_delay = _seconds_until_next_realtime_refresh(frame_cache)
        finally:
            refresh_running = False
            if client_alive():
                schedule_next_refresh(next_delay)

    if client_alive():
        ui.timer(0.1, refresh, once=True)


@ui.page('/graficas/particulas')
async def particles_graph(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    _graph_page('Gráficas Tiempo Real - Partículas', PARTICLE_CHARTS)


@ui.page('/graficas/voc-nox')
async def voc_nox_graph(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    _graph_page('Gráficas Tiempo Real - VOC & NOx', VOC_NOX_CHARTS)


@ui.page('/graficas/ambientales')
async def ambient_graph(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    _graph_page('Gráficas Tiempo Real - CO2, Temperatura & Humedad', AMBIENT_CHARTS)


HISTORY_OPTIONS: dict[str, ChartSpec] = {
    'pm1p0': ChartSpec('pm1p0', 'PM1.0', 'µg/m³', '#ff0000'),
    'pm2p5': ChartSpec('pm2p5', 'PM2.5', 'µg/m³', '#bfa600'),
    'pm4p0': ChartSpec('pm4p0', 'PM4.0', 'µg/m³', '#00bfbf'),
    'pm10p0': ChartSpec('pm10p0', 'PM10.0', 'µg/m³', '#bf00ff'),
    'voc': ChartSpec('voc', 'VOC', 'Index', '#ff8000'),
    'nox': ChartSpec('nox', 'NOx', 'Index', '#00ff00'),
    'co2': ChartSpec('co2', 'CO2', 'ppm', '#990000', round_values=True),
    'temp': ChartSpec('temp', 'Temperatura', '°C', '#006600'),
    'hum': ChartSpec('hum', 'Humedad', '%', '#0000cc', round_values=True),
}

HISTORY_SELECT_OPTIONS = {
    'pm1p0': 'PM1.0',
    'pm2p5': 'PM2.5',
    'pm4p0': 'PM4.0',
    'pm10p0': 'PM10.0',
    'voc': 'VOC',
    'nox': 'NOx',
    'co2': 'CO2',
    'temp': 'Temperatura',
    'hum': 'Humedad',
}


def _interval_label(minutes: int) -> str:
    for label, value in HISTORY_MENU:
        if value == minutes:
            return label
    return f'{minutes} min'


def _history_series_data(frame: Any, spec: ChartSpec, minutes: int) -> tuple[list[str], list[float], list[Any]]:
    import pandas as pd

    if frame.empty or spec.key not in frame:
        return [], [], []

    df = frame[['_dt', spec.key]].copy()
    df[spec.key] = pd.to_numeric(df[spec.key], errors='coerce')
    df = df.dropna(subset=[spec.key])
    if df.empty:
        return [], [], []

    if minutes == SAMPLE_BASE_MIN:
        labels = [_fmt_label(ts) for ts in df['_dt']]
        values = [float(v) for v in df[spec.key]]
        times = list(df['_dt'])
    else:
        rule = '1D' if minutes == 1440 else f'{minutes}min'
        df['_bin'] = df['_dt'].dt.floor(rule)
        grouped = df.groupby('_bin')[spec.key].agg(['mean', 'count']).reset_index()
        required = max(1, math.ceil((minutes / SAMPLE_BASE_MIN) * 0.90))
        grouped = grouped[grouped['count'] >= required]
        labels = [_fmt_label(ts) for ts in grouped['_bin']]
        values = [float(v) for v in grouped['mean']]
        times = list(grouped['_bin'])

    if spec.round_values:
        values = [round(v) for v in values]

    return labels, values, times


def _history_category_ticks(labels: list[str], minutes: int) -> tuple[list[int], list[str]]:
    non_empty = [i for i, label in enumerate(labels) if label]
    if not non_empty:
        return [], []

    max_ticks = 12 if minutes == 1440 else 24
    if len(non_empty) <= max_ticks:
        selected = non_empty
    else:
        step = math.ceil(len(non_empty) / max_ticks)
        selected = non_empty[::step]
        if selected[-1] != non_empty[-1]:
            selected.append(non_empty[-1])

    ticktext: list[str] = []
    previous_date = ''
    for i in selected:
        label = labels[i]
        if ' ' not in label:
            ticktext.append(label)
            continue
        date_part, time_part = label.split(' ', 1)
        if minutes == 1440:
            ticktext.append(date_part)
            continue
        base = time_part[:5]
        if date_part != previous_date:
            ticktext.append(f'{_short_date_label(date_part)}-{base}')
            previous_date = date_part
        else:
            ticktext.append(base)
    return selected, ticktext


def _build_history_figure(labels: list[str], values: list[float], times: list[Any], spec: ChartSpec, minutes: int) -> Any:
    import plotly.graph_objects as go

    display_labels = list(labels)
    display_values: list[float | None] = list(values)
    # Si hay pocos datos, mantener 24 posiciones para evitar barras enormes.
    if len(display_labels) < MAX_BARS:
        missing = MAX_BARS - len(display_labels)
        display_labels.extend([''] * missing)
        display_values.extend([None] * missing)

    finite = [v for v in display_values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]
    upper = max(finite) * 2 if finite and max(finite) > 0 else 1
    x_values = list(range(len(display_labels)))
    tickvals, ticktext = _history_category_ticks(display_labels, minutes)

    fig = go.Figure(data=[go.Bar(x=x_values, y=display_values, name=spec.title, marker={'color': spec.color})])
    fig.update_layout(
        height=600,
        margin={'t': 20, 'l': 60, 'r': 40, 'b': 95 if minutes == 1440 else 150},
        bargap=0.2,
        paper_bgcolor='#cce5dc',
        plot_bgcolor='#cce5dc',
        showlegend=False,
        font={'family': 'Arial', 'color': 'black'},
    )
    fig.update_xaxes(
        type='category',
        tickmode='array',
        tickvals=tickvals,
        ticktext=ticktext,
        tickangle=-30 if minutes == 1440 else -45,
        automargin=True,
        rangeslider={'visible': False},
        showgrid=False,
        zeroline=False,
        showline=True,
        title={
            'text': '<b>Fecha de Medición</b>' if minutes == 1440 else '<b>Fecha y Hora de Medición</b>',
            'font': {'size': 16, 'color': 'black', 'family': 'Arial'},
            'standoff': 46,
        },
        tickfont={'color': 'black', 'size': 13, 'family': 'Arial'},
    )
    fig.update_yaxes(
        title={'text': f'<b>{spec.y_title}</b>', 'font': {'size': 16, 'color': 'black', 'family': 'Arial'}},
        tickfont={'color': 'black', 'size': 14, 'family': 'Arial'},
        rangemode='tozero',
        range=[0, upper],
        fixedrange=False,
        showgrid=False,
        zeroline=False,
        showline=True,
    )
    return fig


def _table_datetime_label(label: str) -> str:
    if ' ' not in label:
        return label or '-'
    date_part, time_part = label.split(' ', 1)
    parts = date_part.split('-')
    if len(parts) == 3:
        date_part = f'{parts[2]}-{parts[1]}-{parts[0]}'
    return f'{date_part} {time_part}'


def _history_table_html(labels: list[str], values: list[float], spec: ChartSpec, minutes: int) -> str:
    unit_label = _interval_label(minutes)
    rows = []
    for idx, (label, value) in enumerate(zip(labels, values)):
        if spec.round_values:
            pretty = str(round(value))
        else:
            pretty = f'{value:.2f}'
        rows.append(f'<tr><td>{idx}</td><td>{_table_datetime_label(label)}</td><td>{pretty}</td></tr>')
    return (
        '<div class="data-table-container">'
        '<table id="uploadTable">'
        '<thead><tr>'
        '<th>#</th>'
        f'<th>Fecha y Hora ({unit_label})</th>'
        f'<th>{spec.title.upper()}</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )


@ui.page('/graficas/historial')
async def history_graph(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    ui.page_title('Gráficas del Historial')
    add_styles()
    _add_graph_styles()

    frame_cache: Any | None = None
    selected_device_id: str | None = None
    current_labels: list[str] = []
    current_values: list[float] = []
    current_times: list[Any] = []
    current_minutes = SAMPLE_BASE_MIN
    visible_start_index = 0
    visible_end_index = 0

    with ui.element('div').classes('dashboard'):
        _nav()
        with ui.element('div').classes('brand-header'):
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
            ui.label('EcoSensor®').classes('brand-name')
        ui.label('Gráficas del Historial').classes('section-title')
        status = ui.label('Cargando historial...').classes('status-line mt-3')

        ui.separator()
        ui.label('Gráfica de Datos Historico').classes('section-title')
        id_label = ui.label('ID: -').classes('section-title')
        with ui.column().classes('history-controls'):
            ui.label('Seleccionar Dato a Graficar:').classes('history-select-label')
            selector = ui.select(HISTORY_SELECT_OPTIONS, value='pm1p0').props('outlined dense').classes('w-full')
        with ui.column().classes('agg-toolbar-wrap'):
            ui.label('Historial').classes('agg-chart-title')

            with ui.column().classes('history-slider-box'):
                ui.label('Seleccione el rango de mediciones a visualizar').classes('history-range-label')
                history_range = (
                    ui.range(
                        min=0,
                        max=0,
                        value={'min': 0, 'max': 0},
                    )
                    .props('label-always left-label-value="-" right-label-value="-"')
                    .classes('w-full')
                )

            ui.label('Seleccione el intervalo de lecturas').classes('agg-toolbar-label')
            interval_buttons: list[Any] = []
            with ui.row().classes('agg-toolbar'):
                for label, minutes in HISTORY_MENU:
                    button = ui.button(label).props('flat no-caps').classes('agg-btn')
                    interval_buttons.append(button)

                    async def select_interval(m: int = minutes) -> None:
                        nonlocal current_minutes
                        current_minutes = m
                        await rebuild()

                    button.on('click', select_interval)

        with ui.element('div').classes('chart-card history-chart-card'):
            chart = ui.plotly({}).classes('w-full').style('height: 620px; max-height: 620px;')
        table = ui.html('').classes('w-full')

    def _visible_history_slice() -> tuple[list[str], list[float], list[Any]]:
        if not current_labels:
            return [], [], []

        start = max(0, min(visible_start_index, len(current_labels) - 1))
        end = max(start, min(visible_end_index, len(current_labels) - 1))
        return (
            current_labels[start:end + 1],
            current_values[start:end + 1],
            current_times[start:end + 1],
        )

    def _update_history_range_labels() -> None:
        if not current_labels:
            history_range._props['left-label-value'] = '-'
            history_range._props['right-label-value'] = '-'
            history_range.update()
            return

        start = max(0, min(visible_start_index, len(current_labels) - 1))
        end = max(start, min(visible_end_index, len(current_labels) - 1))
        history_range._props['left-label-value'] = current_labels[start]
        history_range._props['right-label-value'] = current_labels[end]
        history_range.update()

    def _reset_history_range() -> None:
        nonlocal visible_start_index, visible_end_index

        total = len(current_labels)
        if total <= 0:
            visible_start_index = 0
            visible_end_index = 0
            history_range._props['min'] = 0
            history_range._props['max'] = 0
            history_range.value = {'min': 0, 'max': 0}
            history_range.update()
            _update_history_range_labels()
            return

        visible_start_index = 0
        visible_end_index = total - 1
        history_range._props['min'] = 0
        history_range._props['max'] = total - 1
        history_range.value = {'min': visible_start_index, 'max': visible_end_index}
        history_range.update()
        _update_history_range_labels()

    def update_interval_buttons() -> None:
        for button, (_, minutes) in zip(interval_buttons, HISTORY_MENU):
            if minutes == current_minutes:
                button.classes(add='active')
            else:
                button.classes(remove='active')

    async def redraw() -> None:
        if not current_labels:
            chart.figure = _build_history_figure([], [], [], HISTORY_OPTIONS[str(selector.value)], current_minutes)
            chart.update()
            table.set_content('')
            return

        spec = HISTORY_OPTIONS[str(selector.value)]
        visible_labels, visible_values, visible_times = _visible_history_slice()
        chart.figure = _build_history_figure(visible_labels, visible_values, visible_times, spec, current_minutes)
        chart.update()
        table.set_content(_history_table_html(visible_labels, visible_values, spec, current_minutes))

    async def rebuild() -> None:
        nonlocal current_labels, current_values, current_times
        if frame_cache is None:
            return
        spec = HISTORY_OPTIONS[str(selector.value)]
        current_labels, current_values, current_times = _history_series_data(frame_cache, spec, current_minutes)
        update_interval_buttons()
        _reset_history_range()
        await redraw()

    async def refresh_sensor_options() -> None:
        nonlocal selected_device_id
        await ensure_active_devices()
        options = active_device_options()
        stored_device_id = str(app.storage.user.get('selected_device_id') or '') or None
        if stored_device_id in options:
            selected_device_id = stored_device_id
        elif selected_device_id not in options:
            selected_device_id = next(iter(options)) if options else None
            if selected_device_id:
                app.storage.user['selected_device_id'] = selected_device_id
            else:
                app.storage.user.pop('selected_device_id', None)
        id_label.set_text(f'ID: {device_display_name(selected_device_id) if selected_device_id else "-"}')

    async def load_history() -> None:
        nonlocal frame_cache
        try:
            await refresh_sensor_options()
            if not selected_device_id:
                frame_cache = _rows_to_frame([])
                status.set_text('No hay EcoSensor activos disponibles.')
                await rebuild()
                return
            status.set_text('Cargando historial almacenado...')
            rows = await asyncio.to_thread(graph_rows_all, selected_device_id)
            frame_cache = _rows_to_frame(rows)
            if frame_cache.empty:
                status.set_text('Historial local vacío. No hay registros almacenados para graficar.')
            else:
                total = len(frame_cache)
                last = frame_cache.iloc[-1]
                status.set_text(f'Historial cargado. Registros: {total}. Última medición: {last["fecha"]} {last["hora"]}')
            await rebuild()
        except ModuleNotFoundError as exc:
            status.set_text(f'Falta instalar el paquete Python: {exc.name or "plotly/pandas"}')
        except Exception as exc:
            status.set_text(f'Error al cargar historial: {exc}')

    async def on_history_range_change(event: Any) -> None:
        nonlocal visible_start_index, visible_end_index

        if not current_labels:
            return

        value = event.args if isinstance(event.args, dict) else history_range.value
        if not isinstance(value, dict):
            return

        raw_min = int(value.get('min', 0))
        raw_max = int(value.get('max', len(current_labels) - 1))

        visible_start_index = max(0, min(raw_min, len(current_labels) - 1))
        visible_end_index = max(visible_start_index, min(raw_max, len(current_labels) - 1))

        _update_history_range_labels()
        await redraw()

    history_range.on('update:model-value', on_history_range_change)
    selector.on('update:model-value', lambda: ui.timer(0.1, rebuild, once=True))
    ui.timer(0.1, load_history, once=True)

