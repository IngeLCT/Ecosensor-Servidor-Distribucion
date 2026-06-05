import asyncio
import html
import math
from dataclasses import dataclass, field
from typing import Any

from nicegui import app, events, ui

from services.device_registry import active_device_options, ensure_active_devices, registry_revision
from shared.formatters import device_display_name, format_value
from shared.styles import add_styles
from storage.measurements_store import graph_rows_all

CLUSTER_RADIUS_KM = 5.0
SEARCHING_OPTION = '__searching_ecosensor__'


@dataclass
class LocationCluster:
    index: int
    lat_sum: float = 0.0
    lon_sum: float = 0.0
    count: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def lat(self) -> float:
        return self.lat_sum / self.count if self.count else 0.0

    @property
    def lon(self) -> float:
        return self.lon_sum / self.count if self.count else 0.0

    @property
    def first_label(self) -> str:
        if not self.rows:
            return ''
        row = self.rows[0]
        return f"{row.get('fecha') or ''} {row.get('hora') or ''}".strip()

    @property
    def last_label(self) -> str:
        if not self.rows:
            return ''
        row = self.rows[-1]
        return f"{row.get('fecha') or ''} {row.get('hora') or ''}".strip()

    def add(self, row: dict[str, Any], lat: float, lon: float) -> None:
        self.lat_sum += lat
        self.lon_sum += lon
        self.count += 1
        self.rows.append(row)


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


def _add_location_styles() -> None:
    ui.add_head_html(
        '''
        <style>
        .locations-card {
            width: 100%;
            max-width: 1200px;
            margin: 24px auto;
            background: #cce5dc;
            border-radius: 10px;
            padding: 20px;
            box-sizing: border-box;
        }
        .locations-map {
            width: 100%;
            height: 620px;
        }
        .locations-map .js-plotly-plot,
        .locations-map .plot-container,
        .locations-map .svg-container {
            height: 620px !important;
        }
        .locations-table-wrap {
            width: 100%;
            max-height: 580px;
            overflow: auto;
            margin-top: 14px;
        }
        .locations-table-wrap table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            background: #fff;
        }
        .locations-table-wrap th,
        .locations-table-wrap td {
            border: 1px solid #333;
            padding: 7px 9px;
            text-align: center;
            color: #000;
            font-size: 14px;
            white-space: nowrap;
        }
        .locations-table-wrap thead th {
            position: sticky;
            top: 0;
            z-index: 2;
            background: #e9f4ef;
            font-weight: bold;
        }
        .locations-summary {
            color: #000;
            font-size: 17px;
            font-weight: 600;
            text-align: center;
            margin: 8px 0 4px 0;
        }
        </style>
        '''
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _valid_location_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not row.get('gps_valid'):
            continue
        try:
            lat = float(row.get('gps_lat'))
            lon = float(row.get('gps_lon'))
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        item = dict(row)
        item['_lat'] = lat
        item['_lon'] = lon
        valid.append(item)
    return valid


def _cluster_rows(rows: list[dict[str, Any]]) -> list[LocationCluster]:
    clusters: list[LocationCluster] = []
    for row in rows:
        lat = float(row['_lat'])
        lon = float(row['_lon'])
        match: LocationCluster | None = None
        for cluster in clusters:
            if _haversine_km(lat, lon, cluster.lat, cluster.lon) <= CLUSTER_RADIUS_KM:
                match = cluster
                break
        if match is None:
            match = LocationCluster(index=len(clusters))
            clusters.append(match)
        match.add(row, lat, lon)
    return clusters


def _extract_cluster_index(event: events.GenericEventArguments) -> int | None:
    args = event.args
    try:
        if isinstance(args, dict):
            points = args.get('points') or []
            if points:
                custom = points[0].get('customdata')
                if isinstance(custom, list):
                    custom = custom[0]
                return int(custom)
        if isinstance(args, list) and args:
            custom = args[0].get('customdata')
            if isinstance(custom, list):
                custom = custom[0]
            return int(custom)
    except (TypeError, ValueError, AttributeError, IndexError):
        return None
    return None


def _make_map_figure(clusters: list[LocationCluster], selected_index: int | None = None) -> dict[str, Any]:
    import plotly.graph_objects as go

    if not clusters:
        fig = go.Figure()
        fig.update_layout(
            margin=dict(l=0, r=0, t=35, b=0),
            height=620,
            title='Sin coordenadas GPS válidas para este EcoSensor',
        )
        return fig

    center_lat = sum(cluster.lat * cluster.count for cluster in clusters) / sum(cluster.count for cluster in clusters)
    center_lon = sum(cluster.lon * cluster.count for cluster in clusters) / sum(cluster.count for cluster in clusters)
    max_count = max(cluster.count for cluster in clusters)
    sizes = [max(14, min(46, 14 + 32 * (cluster.count / max_count))) for cluster in clusters]
    colors = ['#d62728' if cluster.index == selected_index else '#1f77b4' for cluster in clusters]

    fig = go.Figure(
        go.Scattermap(
            lat=[cluster.lat for cluster in clusters],
            lon=[cluster.lon for cluster in clusters],
            mode='markers+text',
            text=[str(cluster.count) for cluster in clusters],
            textposition='middle center',
            customdata=[cluster.index for cluster in clusters],
            hovertext=[
                f'Punto {cluster.index + 1}<br>'
                f'Mediciones: {cluster.count}<br>'
                f'Primera: {cluster.first_label}<br>'
                f'Última: {cluster.last_label}<br>'
                f'Centro: {cluster.lat:.6f}, {cluster.lon:.6f}'
                for cluster in clusters
            ],
            marker=dict(size=sizes, color=colors, opacity=0.82),
            hovertemplate='%{hovertext}<extra></extra>',
        )
    )
    fig.update_layout(
        title='Ubicaciones agrupadas por radio de 5 km',
        height=620,
        margin=dict(l=0, r=0, t=42, b=0),
        map=dict(style='open-street-map', center=dict(lat=center_lat, lon=center_lon), zoom=10),
        clickmode='event+select',
        showlegend=False,
    )
    return fig


def _fmt(value: Any, decimals: int = 2) -> str:
    return html.escape(format_value(value, decimals))


def _render_measurements_table(cluster: LocationCluster | None) -> str:
    if cluster is None:
        return '<div class="locations-summary">Selecciona un punto en el mapa para ver sus mediciones.</div>'

    rows_html = []
    for row in cluster.rows:
        rows_html.append(
            '<tr>'
            f'<td>{html.escape(str(row.get("fecha") or ""))}</td>'
            f'<td>{html.escape(str(row.get("hora") or ""))}</td>'
            f'<td>{_fmt(row.get("pm1p0"))}</td>'
            f'<td>{_fmt(row.get("pm2p5"))}</td>'
            f'<td>{_fmt(row.get("pm4p0"))}</td>'
            f'<td>{_fmt(row.get("pm10p0"))}</td>'
            f'<td>{_fmt(row.get("voc"))}</td>'
            f'<td>{_fmt(row.get("nox"))}</td>'
            f'<td>{_fmt(row.get("co2"), 0)}</td>'
            f'<td>{_fmt(row.get("temp"))}</td>'
            f'<td>{_fmt(row.get("hum"), 0)}</td>'
            '</tr>'
        )

    summary = (
        f'<div class="locations-summary">Punto {cluster.index + 1}: '
        f'{cluster.count} mediciones | '
        f'Primera: {html.escape(cluster.first_label)} | '
        f'Última: {html.escape(cluster.last_label)} | '
        f'Centro: {cluster.lat:.6f}, {cluster.lon:.6f}</div>'
    )
    return (
        summary
        + '<div class="locations-table-wrap"><table>'
        + '<thead><tr>'
        + '<th>Fecha</th><th>Hora</th><th>PM1.0</th><th>PM2.5</th><th>PM4.0</th><th>PM10.0</th>'
        + '<th>VOC</th><th>NOx</th><th>CO2</th><th>Temperatura</th><th>Humedad</th>'
        + '</tr></thead><tbody>'
        + ''.join(rows_html)
        + '</tbody></table></div>'
    )


@ui.page('/ubicaciones')
def locations_page() -> None:
    ui.page_title('EcoSensor Ubicaciones')
    add_styles()
    _add_location_styles()

    selected_device_id: str | None = str(app.storage.user.get('selected_device_id') or '') or None
    seen_registry_revision = {'value': registry_revision()}
    clusters: list[LocationCluster] = []
    selected_cluster_index: int | None = None

    with ui.element('div').classes('dashboard'):
        _nav()
        with ui.element('div').classes('brand-header'):
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
            ui.label('EcoSensor®').classes('brand-name')

        ui.label('Ubicaciones').classes('section-title dashboard-main-title')
        with ui.row().classes('items-center justify-center gap-3 history-controls'):
            ui.label('ID:').classes('section-title')
            sensor_select = ui.select({}, value=None).props('outlined dense').classes('w-64 device-select')

        with ui.element('div').classes('locations-card'):
            status = ui.label('').classes('locations-summary')
            chart = ui.plotly({}).classes('locations-map')
            table = ui.html('').classes('w-full')

    async def refresh_sensor_options() -> None:
        nonlocal selected_device_id
        options = active_device_options()
        if not options:
            asyncio.create_task(ensure_active_devices())
        stored_device_id = str(app.storage.user.get('selected_device_id') or '') or None
        if stored_device_id:
            selected_device_id = stored_device_id
        sensor_select.options = options
        if not options:
            selected_device_id = None
            app.storage.user.pop('selected_device_id', None)
            sensor_select.options = {SEARCHING_OPTION: 'Buscando ecosensor'}
            sensor_select.value = SEARCHING_OPTION
            sensor_select.disable()
            sensor_select.update()
            return
        sensor_select.enable()
        if selected_device_id not in options:
            selected_device_id = next(iter(options))
            app.storage.user['selected_device_id'] = selected_device_id
        sensor_select.value = selected_device_id
        sensor_select.update()

    async def refresh_locations() -> None:
        nonlocal clusters, selected_cluster_index
        if not selected_device_id:
            clusters = []
            selected_cluster_index = None
            status.set_text('No hay EcoSensor seleccionado.')
            chart.figure = _make_map_figure([])
            chart.update()
            table.set_content(_render_measurements_table(None))
            return

        try:
            rows = await asyncio.to_thread(graph_rows_all, selected_device_id)
            location_rows = _valid_location_rows(rows)
            clusters = _cluster_rows(location_rows)
        except ModuleNotFoundError as exc:
            status.set_text(f'Falta instalar el paquete Python: {exc.name or "plotly"}')
            return

        if selected_cluster_index is not None and selected_cluster_index >= len(clusters):
            selected_cluster_index = None

        try:
            chart.figure = _make_map_figure(clusters, selected_cluster_index)
            chart.update()
        except ModuleNotFoundError as exc:
            status.set_text(f'Falta instalar el paquete Python: {exc.name or "plotly"}')
            return
        except Exception as exc:
            status.set_text(f'No se pudo dibujar el mapa: {exc}')
            table.set_content(_render_measurements_table(None))
            return

        if clusters:
            display_name = device_display_name(selected_device_id)
            status.set_text(f'{display_name}: {len(location_rows)} mediciones con GPS válido agrupadas en {len(clusters)} punto(s).')
        else:
            status.set_text(f'{device_display_name(selected_device_id)} no tiene mediciones con GPS válido todavía.')
        table.set_content(_render_measurements_table(clusters[selected_cluster_index] if selected_cluster_index is not None and selected_cluster_index < len(clusters) else None))

    async def on_sensor_change(event: Any) -> None:
        nonlocal selected_device_id, selected_cluster_index
        if event.value == SEARCHING_OPTION:
            return
        selected_device_id = str(event.value or '') or None
        selected_cluster_index = None
        if selected_device_id:
            app.storage.user['selected_device_id'] = selected_device_id
        else:
            app.storage.user.pop('selected_device_id', None)
        await refresh_locations()

    async def on_map_click(event: events.GenericEventArguments) -> None:
        nonlocal selected_cluster_index
        index = _extract_cluster_index(event)
        if index is None or index < 0 or index >= len(clusters):
            return
        selected_cluster_index = index
        try:
            chart.figure = _make_map_figure(clusters, selected_cluster_index)
            chart.update()
        except ModuleNotFoundError as exc:
            status.set_text(f'Falta instalar el paquete Python: {exc.name or "plotly"}')
            return
        except Exception as exc:
            status.set_text(f'No se pudo actualizar el mapa: {exc}')
            return
        table.set_content(_render_measurements_table(clusters[selected_cluster_index]))

    async def refresh_if_registry_changed() -> None:
        current = registry_revision()
        if current != seen_registry_revision['value']:
            seen_registry_revision['value'] = current
            await refresh_sensor_options()
            await refresh_locations()

    sensor_select.on_value_change(on_sensor_change)
    chart.on('plotly_click', on_map_click)
    ui.timer(1.0, refresh_if_registry_changed)
    ui.timer(0.1, lambda: asyncio.create_task(refresh_sensor_options()), once=True)
    ui.timer(0.2, lambda: asyncio.create_task(refresh_locations()), once=True)
