from typing import Any

from fastapi import Request
from nicegui import Client, app, ui

from services.device_registry import active_device_options, ensure_active_devices, ensure_device_active, forget_device, host_for_device, probe_host, registry_revision, remember_host
from services.main_window import register_main_window
from services.esp_client import sync_time_if_needed
from services.measurement_sync import coordinated_clear_history
from services.wifi_manager import clear_device_wifi
from shared.formatters import device_display_name
from shared.styles import add_styles

LOCAL_CLIENTS = {'127.0.0.1', '::1', 'localhost'}


def is_local_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ''
    return client_host in LOCAL_CLIENTS


@ui.page('/')
async def index(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    ui.navigate.to('/dashboard')


@ui.page('/config')
async def config_page(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    ui.page_title('Configurar EcoSensor Servidor')
    add_styles()

    if not is_local_request(request):
        with ui.element('div').classes('connect-shell'):
            with ui.element('div').classes('connect-card'):
                ui.label('Acceso restringido').classes('connect-title')
                ui.label('Esta configuración solo se puede abrir desde el equipo servidor.').classes('connect-label')
                ui.label('Usa: http://localhost:8765/config').classes('connect-label')
        return

    selected_device_id: str | None = str(app.storage.user.get('selected_device_id') or '') or None
    seen_registry_revision = {'value': registry_revision()}

    with ui.element('div').classes('connect-shell'):
        with ui.element('div').classes('connect-card'):
            with ui.element('div').classes('brand-header'):
                ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
                ui.label('EcoSensor®').classes('brand-name')
            with ui.element('div').classes('connect-box'):
                ui.label('Seleccione el EcoSensor a configurar').classes('connect-label')
                sensor_select = ui.select({}, value=None).props('outlined dense').classes('w-full connect-input device-select')
                selected_host_info = ui.label('').classes('connect-label')
                with ui.row().classes('justify-center gap-3'):
                    refresh_button = ui.button('Actualizar lista').props('unelevated no-caps').classes('secondary-button action-button')
                    connect_button = ui.button('Sincronizar hora').props('unelevated no-caps').classes('connect-button action-button')
                ui.button('Ir al dashboard', on_click=lambda: ui.navigate.to('/dashboard')).props('flat no-caps').classes('dashboard-link')

            with ui.element('div').classes('connect-box'):
                ui.label('Mantenimiento').classes('connect-label')
                ui.label('Acciones disponibles solo desde el equipo servidor. Úsalas con cuidado.').classes('connect-label')
                with ui.row().classes('justify-center gap-3'):
                    clear_wifi_button = ui.button('Borrar datos de WiFi').props('unelevated color=negative text-color=white no-caps').classes('danger-outline-button action-button')
                    clear_history_button = ui.button('Borrar historial de mediciones').props('unelevated color=negative text-color=white no-caps').classes('danger-button action-button')

    async def refresh_sensor_options() -> None:
        nonlocal selected_device_id
        devices = await ensure_active_devices()
        options = active_device_options()
        stored_device_id = str(app.storage.user.get('selected_device_id') or '') or None
        if stored_device_id in options:
            selected_device_id = stored_device_id
        elif selected_device_id not in options:
            selected_device_id = next(iter(options)) if options else None

        sensor_select.options = options
        sensor_select.value = selected_device_id
        sensor_select.update()

        if selected_device_id:
            app.storage.user['selected_device_id'] = selected_device_id
            active = next((item for item in devices if item.get('device_id') == selected_device_id), None)
            selected_host = str((active or {}).get('host') or host_for_device(selected_device_id))
            selected_host_info.set_text(f'Host detectado: {selected_host}')
        else:
            app.storage.user.pop('selected_device_id', None)
            selected_host_info.set_text('No hay EcoSensores activos detectados todavía.')

    async def selected_host() -> tuple[str | None, str | None]:
        if not selected_device_id:
            await refresh_sensor_options()
        if not selected_device_id:
            ui.notify('No hay EcoSensor seleccionado.', color='negative')
            return None, None

        active = await ensure_device_active(selected_device_id)
        host = str((active or {}).get('host') or host_for_device(selected_device_id))
        if not host:
            ui.notify('No se encontró el host del EcoSensor seleccionado.', color='negative')
            return selected_device_id, None
        return selected_device_id, host

    async def connect() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return

        display_name = device_display_name(device_id)
        detected = await probe_host(host, timeout=1.5)
        if not detected:
            ui.notify(f'No se pudo conectar a {display_name}. Revisa red/mDNS.', color='negative')
            return

        detected_host = str(detected.get('host') or host)
        result = await sync_time_if_needed(detected_host, timeout=3.0)
        if result.get('synced'):
            ui.notify(f'{display_name} conectado y fecha/hora sincronizada.', color='positive')
        elif result.get('ok'):
            ui.notify(f'{display_name} conectado con fecha/hora válida.', color='positive')
        else:
            ui.notify(f'{display_name} conectado; la hora no se pudo sincronizar, pero se guardó para mediciones.', color='warning')

        remember_host(detected_host, str(detected.get('device_id') or device_id))
        app.storage.user['selected_device_id'] = str(detected.get('device_id') or device_id)
        await refresh_sensor_options()

    async def clear_wifi() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return
        display_name = device_display_name(device_id)
        with ui.dialog() as dialog, ui.card():
            ui.label(f'¿Borrar credenciales WiFi de {display_name}?')
            ui.label(f'{display_name} reiniciará y volverá al modo de configuración WiFi.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await clear_device_wifi(device_id, host)
                    if result.get('ok'):
                        forget_device(device_id)
                        if app.storage.user.get('selected_device_id') == device_id:
                            app.storage.user.pop('selected_device_id', None)
                        if result.get('confirmed'):
                            ui.notify(f'Credenciales WiFi borradas en {device_display_name(device_id)}. Quitado de las listas activas.', color='positive')
                        else:
                            ui.notify(
                                f'Orden de borrado enviada a {device_display_name(device_id)}. '
                                'El equipo cortó la conexión al reiniciarse; verifica que aparezca su red de configuración.',
                                color='warning',
                            )
                        await refresh_sensor_options()
                    else:
                        ui.notify(f'No se pudo borrar WiFi: {result.get("message") or result.get("error")}', color='negative')

                ui.button('Borrar WiFi', on_click=confirm).props('unelevated color=negative')
        dialog.open()

    async def clear_history() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return
        display_name = device_display_name(device_id)
        with ui.dialog() as dialog, ui.card():
            ui.label(f'¿Borrar TODO el historial de mediciones de {display_name}?')
            ui.label(f'Se borrará el CSV de la SD de {display_name} y su base local SQLite del servidor.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await coordinated_clear_history(device_id)
                    if not result.get('ok'):
                        ui.notify(f'No se pudo completar el borrado coordinado de {display_name}: {result.get("error")}', color='negative')
                        return
                    target_device_id = str(result.get('device_id') or device_id)
                    deleted = int(result.get('deleted') or 0)
                    ui.notify(f'Historial de {device_display_name(target_device_id)} borrado. Filas locales eliminadas: {deleted}.', color='positive')
                    await refresh_sensor_options()

                ui.button('Borrar historial', on_click=confirm).props('unelevated color=negative')
        dialog.open()

    async def on_sensor_change(event: Any) -> None:
        nonlocal selected_device_id
        selected_device_id = str(event.value or '') or None
        if selected_device_id:
            app.storage.user['selected_device_id'] = selected_device_id
        else:
            app.storage.user.pop('selected_device_id', None)
        await refresh_sensor_options()

    async def refresh_options_if_registry_changed() -> None:
        current = registry_revision()
        if current != seen_registry_revision['value']:
            seen_registry_revision['value'] = current
            await refresh_sensor_options()

    sensor_select.on_value_change(on_sensor_change)
    refresh_button.on('click', refresh_sensor_options)
    connect_button.on('click', connect)
    clear_wifi_button.on('click', clear_wifi)
    clear_history_button.on('click', clear_history)
    ui.timer(1.0, refresh_options_if_registry_changed)
    ui.timer(0.1, refresh_sensor_options, once=True)
