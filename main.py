"""Punto de entrada para EcoSensor Servidor - versión de distribución.

Esta variante excluye actualizaciones integradas y herramientas internas de diagnóstico.
"""
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')

if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

if sys.stdin is None:
    sys.stdin = open(os.devnull, 'r', encoding='utf-8')

import asyncio
import time

from services.windows_asyncio import install_connection_reset_filter, install_windows_selector_policy

install_windows_selector_policy()

from config import DEVICE_ID, STATIC_DIR, UI_HOST, UI_PORT, UI_FALLBACK_PORT

from fastapi import Query, Request
from fastapi.responses import JSONResponse, Response
from nicegui import app, ui
from services.device_registry import ensure_active_devices, mark_device_seen, normalize_device_id, probe_failures, remember_host
from services.measurement_sync import background_sync_loop, is_history_syncing, schedule_preventive_history_sync, sync_before_csv_download
from services.main_window import open_main_browser
from services.mdns_service import start_mdns_service
from shared.formatters import row_from_payload
from storage.measurements_store import graph_latest_row, graph_rows_count, graph_rows_history, graph_rows_page, graph_rows_since, measurements_csv_text, save_measurement, validate_measurements_for_csv
import socket

def _register_pages() -> None:
    """Carga módulos de páginas NiceGUI que registran rutas al importarse."""
    import pages.connect_page
    import pages.dashboard_page
    import pages.graphs_page
    import pages.locations_page


_register_pages()

app.add_static_files('/static', STATIC_DIR)

@app.get('/api/health')
async def api_health() -> JSONResponse:
    return JSONResponse({'ok': True, 'service': 'EcoSensor Servidor'})

_background_sync_task: asyncio.Task | None = None


def _start_background_sync() -> None:
    global _background_sync_task
    install_connection_reset_filter()
    if _background_sync_task is None or _background_sync_task.done():
        _background_sync_task = asyncio.create_task(background_sync_loop())

def _can_bind_port(host: str, port: int) -> bool:
    test_host = host if host not in {'', '0.0.0.0'} else '0.0.0.0'

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((test_host, port))
            return True
    except OSError:
        return False


def _select_ui_port() -> int:
    if _can_bind_port(UI_HOST, UI_PORT):
        print(f'Puerto seleccionado: {UI_PORT}', flush=True)
        return UI_PORT

    print(f'ADVERTENCIA: el puerto {UI_PORT} no esta disponible. Intentando puerto {UI_FALLBACK_PORT}.', flush=True)

    if _can_bind_port(UI_HOST, UI_FALLBACK_PORT):
        print(f'Puerto seleccionado: {UI_FALLBACK_PORT}', flush=True)
        return UI_FALLBACK_PORT

    raise RuntimeError(
        f'No se pudo iniciar EcoSensor: los puertos {UI_PORT} y {UI_FALLBACK_PORT} no estan disponibles.'
    )

SELECTED_UI_PORT = _select_ui_port()

async def _wait_until_http_ready(timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', SELECTED_UI_PORT),
                timeout=1.0,
            )

            request = (
                'GET /api/health HTTP/1.1\r\n'
                f'Host: 127.0.0.1:{SELECTED_UI_PORT}\r\n'
                'Connection: close\r\n'
                '\r\n'
            )
            writer.write(request.encode('ascii'))
            await writer.drain()

            response = await asyncio.wait_for(reader.read(512), timeout=1.0)

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            if b'200 OK' in response:
                return True

        except Exception:
            await asyncio.sleep(0.2)

    return False


async def _start_public_access_when_ready() -> None:
    ready = await _wait_until_http_ready()

    if not ready:
        print(
            'ADVERTENCIA: EcoSensor no confirmo /api/health a tiempo. '
            'Se continuara con el arranque normal.',
            flush=True,
        )

    try:
        await asyncio.to_thread(start_mdns_service, SELECTED_UI_PORT)
    except Exception as exc:
        print(f'ADVERTENCIA: no se pudo iniciar mDNS: {exc!r}', flush=True)

    await asyncio.sleep(0.8)

    try:
        await asyncio.to_thread(open_main_browser, SELECTED_UI_PORT)
    except Exception as exc:
        print(f'ADVERTENCIA: no se pudo abrir el navegador: {exc!r}', flush=True)

def _schedule_public_access_startup() -> None:
    asyncio.create_task(_start_public_access_when_ready())

app.on_startup(_start_background_sync)
app.on_startup(_schedule_public_access_startup)

@app.get('/api/devices')
async def devices_status() -> JSONResponse:
    active = await ensure_active_devices()
    return JSONResponse({'ok': True, 'active': active, 'failures': probe_failures()})


@app.post('/api/measurements/push')
async def api_measurements_push(request: Request) -> JSONResponse:
    """Recibe una medición promedio enviada directamente por un EcoSensor."""
    try:
        payload = await request.json()
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': f'invalid_json: {exc}'}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({'ok': False, 'error': 'json_object_required'}, status_code=400)

    row = row_from_payload(payload)
    if not row:
        return JSONResponse({'ok': False, 'error': 'empty_payload'}, status_code=400)

    device_id = normalize_device_id(row.get('id') or row.get('device_id'))
    if not device_id:
        return JSONResponse({'ok': False, 'error': 'invalid_device_id'}, status_code=400)

    row['id'] = device_id
    row['device_id'] = device_id
    if not row.get('timestamp'):
        row['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
        row['time_valid'] = False
        row['time_source'] = 'estimated_push'
    elif not row.get('time_source'):
        row['time_source'] = 'esp_push'

    client_host = request.client.host if request.client else ''
    host = client_host or f'{device_id}.local'
    if client_host:
        remember_host(client_host, device_id)
    mark_device_seen(device_id, host, {'device_id': device_id, 'ip': client_host})

    gps_valid = bool(row.get('gps_valid'))
    gps_lat = row.get('gps_lat') if gps_valid else None
    gps_lon = row.get('gps_lon') if gps_valid else None
    gps_text = f"GPS=valid lat={gps_lat:.6f} lon={gps_lon:.6f}" if gps_lat is not None and gps_lon is not None else 'GPS=sin_fix'

    print(
        '[push_measurement] '
        f"{device_id} | "
        f"measurement_id={row.get('measurement_id')} | "
        f"timestamp={row.get('timestamp')} | "
        f"PM1.0={row.get('pm1p0')} | "
        f"PM2.5={row.get('pm2p5')} | "
        f"PM4.0={row.get('pm4p0')} | "
        f"PM10.0={row.get('pm10p0')} | "
        f"VOC={row.get('voc')} | "
        f"NOx={row.get('nox')} | "
        f"CO2={row.get('co2')} | "
        f"Temperatura={row.get('temp')} | "
        f"Humedad={row.get('hum')} | "
        f"{gps_text}",
        flush=True,
    )

    inserted = await asyncio.to_thread(save_measurement, host, row)
    schedule_preventive_history_sync(device_id)
    return JSONResponse({
        'ok': True,
        'inserted': inserted,
        'device_id': device_id,
        'measurement_id': row.get('measurement_id'),
    })


@app.post('/api/measurements/sync-before-download')
async def api_sync_before_download(device_id: str | None = Query(default=None)) -> JSONResponse:
    result = await sync_before_csv_download(device_id)
    status_code = 200 if result.get('ok') else int(result.get('status_code') or 409)
    return JSONResponse(result, status_code=status_code)


@app.get('/api/measurements.csv')
async def download_measurements_csv(device_id: str | None = Query(default=None)) -> Response:
    filename_id = normalize_device_id(device_id, default=DEVICE_ID)
    if not filename_id:
        return Response(
            content='device_id inválido. Usa ecosensor01 a ecosensor12.\n',
            media_type='text/plain; charset=utf-8',
            status_code=400,
        )
    if is_history_syncing(filename_id):
        return Response(
            content=(
                'La sincronizacion de historial de este EcoSensor sigue en curso.\n'
                'Espera a que termine y vuelve a descargar el CSV.\n'
            ),
            media_type='text/plain; charset=utf-8',
            status_code=409,
        )

    # Defensa principal: incluso si el botón o el navegador llaman directo al CSV,
    # primero sincronizar, reparar fechas/hora y validar. Nunca entregar CSV malo.
    sync_result = await sync_before_csv_download(filename_id)
    if not sync_result.get('ok'):
        return Response(
            content=sync_result.get('message', 'No se puede descargar el CSV porque hay datos inválidos.') + '\n',
            media_type='text/plain; charset=utf-8',
            status_code=int(sync_result.get('status_code') or 409),
        )

    validation = validate_measurements_for_csv(filename_id)
    if not validation.get('ok'):
        return Response(
            content=validation.get('message', 'No se puede descargar el CSV porque hay datos inválidos.') + '\n',
            media_type='text/plain; charset=utf-8',
            status_code=409,
        )
    return Response(
        content=measurements_csv_text(filename_id),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename_id}_mediciones.csv"'},
    )


@app.get('/api/graph_read')
def graph_read(
    op: str = Query(default='history'),
    id: int = Query(default=0),
    limit: int = Query(default=5000),
    offset: int = Query(default=0),
    device_id: str | None = Query(default=None),
) -> JSONResponse:
    if op == 'latest':
        return JSONResponse({'ok': True, 'row': graph_latest_row(device_id)})
    if op == 'history':
        return JSONResponse({'ok': True, 'rows': graph_rows_history(limit, device_id)})
    if op == 'history_count':
        return JSONResponse({'ok': True, 'total': graph_rows_count(device_id)})
    if op == 'history_page':
        return JSONResponse({'ok': True, 'offset': offset, 'limit': limit, 'rows': graph_rows_page(offset, limit, device_id)})
    if op == 'since':
        return JSONResponse({'ok': True, 'rows': graph_rows_since(id, limit, device_id)})
    return JSONResponse({'ok': False, 'error': 'unknown_op', 'allowed': 'latest|history|history_count|history_page|since'}, status_code=400)


ui.run(
    host=UI_HOST,
    port=SELECTED_UI_PORT,
    title='EcoSensor',
    reload=False,
    show=False,
    reconnect_timeout=30.0,
    storage_secret='ecosensor-local',
)
