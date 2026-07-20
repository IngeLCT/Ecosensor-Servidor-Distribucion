import asyncio
import base64
from io import BytesIO
from typing import Any

import qrcode
import qrcode.image.svg
from fastapi import Request
from nicegui import Client, app, ui

from config import get_selected_ui_port
from services.device_registry import active_device_options, ensure_active_devices, registry_revision
from services.main_window import register_main_window
from services.measurement_sync import schedule_preventive_history_sync, sync_before_csv_download, sync_sensor_measurements
from shared.formatters import format_value
from shared.styles import add_styles
from shared.time_utils import visible_date_time
from storage.measurements_store import get_latest_measurement
from pages.pollutants_modal import pollutants_info_card


def _local_access_url() -> tuple[str, str]:
    port = get_selected_ui_port()
    address = 'ecosensor.local' if port == 80 else f'ecosensor.local:{port}'
    return address, f'http://{address}'


def _qr_data_url(target_url: str) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(target_url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    output = BytesIO()
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode('ascii')
    return f'data:image/svg+xml;base64,{encoded}'


def _add_dashboard_styles() -> None:
    ui.add_head_html(
        '''
        <style>
        .dashboard-hero {
            display: grid;
            grid-template-columns: minmax(190px, 250px) minmax(420px, 1fr) minmax(190px, 250px);
            align-items: center;
            gap: 20px;
            margin-bottom: 18px;
        }
        .dashboard-heading {
            grid-column: 2;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .dashboard-qr-card {
            grid-column: 1;
            grid-row: 1;
            align-items: center;
            justify-self: center;
            gap: 5px;
            color: #040434;
        }
        .dashboard-qr-title {
            font-size: 20px;
            font-weight: 800;
        }
        .dashboard-qr-image {
            width: 170px !important;
            height: 170px !important;
            padding: 7px;
            background: #fff;
            border: 2px solid #040434;
            border-radius: 8px;
        }
        .dashboard-qr-link {
            color: #0645ad !important;
            font-size: 18px;
            font-weight: 800;
            text-decoration: underline;
        }
        @media (max-width: 900px) {
            .dashboard-hero {
                display: flex;
                flex-direction: column;
            }
            .dashboard-heading,
            .dashboard-qr-card {
                width: 100%;
            }
        }
        </style>
        '''
    )


@ui.page('/dashboard')
async def dashboard(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    ui.page_title('EcoSensor Mediciones')
    add_styles()
    _add_dashboard_styles()

    selected_device_id: str | None = None
    searching_option = '__searching_ecosensor__'
    seen_registry_revision = {'value': registry_revision()}
    quick_sync_tasks: dict[str, asyncio.Task] = {}
    local_address, local_url = _local_access_url()
    qr_data_url = _qr_data_url(local_url)

    with ui.element('div').classes('dashboard'):
        with ui.element('nav').classes('top-nav'):
            ui.link('Inicio', '/dashboard')
            ui.label('|')
            ui.link('Gráficas Partículas', '/graficas/particulas')
            ui.label('|')
            ui.link('Gráficas VOC & NOx', '/graficas/voc-nox')
            ui.label('|')
            ui.link('Gráficas CO2, Temperatura & Humedad', '/graficas/ambientales')
            ui.label('|')
            ui.link('Ubicaciones', '/ubicaciones')
            ui.label('|')
            ui.link('Gráficas del Historial', '/graficas/historial')

        with ui.element('div').classes('dashboard-hero'):
            with ui.column().classes('dashboard-qr-card'):
                ui.label('Escanea para acceder').classes('dashboard-qr-title')
                ui.image(qr_data_url).props('fit=contain no-spinner').classes('dashboard-qr-image')
                ui.link(local_address, local_url, new_tab=True).classes('dashboard-qr-link')

            with ui.element('div').classes('dashboard-heading'):
                with ui.element('div').classes('brand-header'):
                    ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
                    ui.label('EcoSensor®').classes('brand-name')

                ui.label('Mediciones Ambientales').classes('section-title dashboard-main-title')
                with ui.row().classes('items-center justify-center gap-3 history-controls'):
                    ui.label('ID:').classes('section-title')
                    sensor_select = ui.select({}, value=None).props('outlined dense').classes('w-64 device-select')

        pollutants_info_card()

        table = ui.html('').classes('w-full')
        date_info = ui.html('').classes('status-line mt-6')
        time_info = ui.html('').classes('status-line')
        connection_info = ui.label('').classes('status-line mt-3')
        with ui.row().classes('justify-center gap-3 mt-4'):
            csv_button = ui.button('Descargar CSV').props('unelevated no-caps').classes('button1')
            analytics_button = ui.button(
                'EcoSensor - Analitica',
                on_click=lambda: ui.navigate.to('https://ecosensor.streamlit.app/', new_tab=True),
            ).props('unelevated no-caps').classes('button1')

    def render_table(row: dict[str, Any] | None) -> None:
        if not row:
            table.set_content('')
            return

        rows = [
            ('PM1.0', format_value(row.get('pm1p0')), 'ug/m3'),
            ('PM2.5', format_value(row.get('pm2p5')), 'ug/m3'),
            ('PM4.0', format_value(row.get('pm4p0')), 'ug/m3'),
            ('PM10.0', format_value(row.get('pm10p0')), 'ug/m3'),
            ('VOC', format_value(row.get('voc')), 'Index'),
            ('NOx', format_value(row.get('nox')), 'Index'),
            ('CO2', format_value(row.get('co2'), 0), 'ppm'),
            ('Temperatura', format_value(row.get('temp')), 'C'),
            ('Humedad Relativa', format_value(row.get('hum'), 0), '%'),
        ]
        html_rows = ''.join(f'<tr><td>{name}</td><td>{value}</td><td>{unit}</td></tr>' for name, value, unit in rows)
        table.set_content(
            '<table class="measure-table">'
            '<tr><th>Mediciones</th><th>Valor</th><th>Unidad</th></tr>'
            f'{html_rows}'
            '</table>'
        )

    def format_date_dd_mm_yyyy(date_value: str) -> str:
        value = (date_value or '').strip()
        if not value:
            return ''
        normalized = value.replace('.', '-').replace('/', '-')
        parts = normalized.split('-')
        if len(parts) >= 3 and len(parts[0]) == 4:
            return f'{parts[2].zfill(2)}-{parts[1].zfill(2)}-{parts[0]}'
        return value

    def split_timestamp(timestamp: str) -> tuple[str, str]:
        date_part, time_part = visible_date_time(timestamp)
        return format_date_dd_mm_yyyy(date_part), time_part

    async def refresh_sensor_options() -> None:
        nonlocal selected_device_id
        # No bloquear el dashboard esperando mDNS/LAN/histórico. Si todavía no
        # hay sensores activos en memoria, lanza la detección en segundo plano;
        # los push_measurement también marcan dispositivos activos al instante.
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
            sensor_select.options = {searching_option: 'Buscando ecosensor'}
            sensor_select.value = searching_option
            sensor_select.disable()
            sensor_select.update()
            return
        sensor_select.enable()
        if selected_device_id not in options:
            selected_device_id = next(iter(options))
            app.storage.user['selected_device_id'] = selected_device_id
        sensor_select.value = selected_device_id
        sensor_select.update()

    async def refresh_from_sqlite() -> None:
        if not selected_device_id:
            render_table(None)
            date_info.set_content('')
            time_info.set_content('')
            connection_info.set_text('')
            return

        row = await asyncio.to_thread(get_latest_measurement, selected_device_id)
        render_table(row)
        timestamp = (row or {}).get('timestamp') or ''
        date_part, time_part = split_timestamp(timestamp)
        date_info.set_content(f'<strong>Fecha última medición:</strong> {date_part}' if date_part else '')
        time_info.set_content(f'<strong>Hora última medición:</strong> {time_part}' if time_part else '')
        if row:
            connection_info.set_text('')
        else:
            connection_info.set_text('EcoSensor activo, sin mediciones almacenadas todavía.')

    async def download_csv_after_sync() -> None:
        if not selected_device_id:
            ui.notify('Selecciona un EcoSensor antes de descargar CSV.', type='warning')
            return

        csv_button.disable()
        ui.notify('Sincronizando historial antes de descargar CSV…', type='info')
        try:
            result = await sync_before_csv_download(selected_device_id)
            if not result.get('ok'):
                message = str(result.get('message') or result.get('error') or 'No se pudo sincronizar el historial.')
                pending = result.get('pending')
                if pending:
                    message = f'{message} Pendientes: {pending}.'
                ui.notify(message, type='negative', multi_line=True)
                return
            await refresh_from_sqlite()
            ui.notify('Historial sincronizado. Descargando CSV…', type='positive')
            ui.navigate.to(f'/api/measurements.csv?device_id={selected_device_id}')
        finally:
            csv_button.enable()

    csv_button.on_click(download_csv_after_sync)

    def schedule_quick_sync(device_id: str | None) -> None:
        if not device_id:
            return
        existing = quick_sync_tasks.get(device_id)
        if existing and not existing.done():
            return
        quick_sync_tasks[device_id] = asyncio.create_task(
            sync_sensor_measurements(device_id, fetch_latest=True, sync_history=False)
        )
        schedule_preventive_history_sync(device_id, delay_seconds=5.0)

    async def sync_then_refresh() -> None:
        await refresh_sensor_options()
        schedule_quick_sync(selected_device_id)
        await refresh_from_sqlite()

    async def refresh_options_and_data() -> None:
        await refresh_sensor_options()
        await refresh_from_sqlite()

    async def on_sensor_change(event: Any) -> None:
        nonlocal selected_device_id
        if event.value == searching_option:
            return
        selected_device_id = str(event.value or '') or None
        if selected_device_id:
            app.storage.user['selected_device_id'] = selected_device_id
        else:
            app.storage.user.pop('selected_device_id', None)
        schedule_quick_sync(selected_device_id)
        await refresh_from_sqlite()

    async def refresh_if_registry_changed() -> None:
        current = registry_revision()
        if current != seen_registry_revision['value']:
            seen_registry_revision['value'] = current
            await refresh_sensor_options()
            schedule_quick_sync(selected_device_id)
            await refresh_from_sqlite()

    sensor_select.on_value_change(on_sensor_change)
    ui.timer(1.0, refresh_if_registry_changed)
    ui.timer(10.0, refresh_from_sqlite)
    ui.timer(0.1, sync_then_refresh, once=True)
