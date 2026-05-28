"""Punto de entrada para EcoSensor Servidor - versión de distribución.

Esta variante excluye actualizaciones integradas y herramientas internas de diagnóstico.
"""

import asyncio
import importlib
import time

from services.windows_asyncio import install_connection_reset_filter, install_windows_selector_policy

install_windows_selector_policy()

from fastapi import Query, Request
from fastapi.responses import JSONResponse, Response
from nicegui import app, ui

from config import STATIC_DIR, UI_HOST, UI_PORT
from services.device_registry import active_devices, mark_device_seen, probe_failures, remember_host
from services.measurement_sync import background_sync_loop
from services.mdns_service import start_mdns_service
from shared.formatters import row_from_payload
from storage.measurements_store import graph_latest_row, graph_rows_history, graph_rows_since, measurements_csv_text, save_measurement


def _register_pages() -> None:
    """Carga módulos de páginas NiceGUI que registran rutas al importarse."""
    for module_name in ('pages.connect_page', 'pages.dashboard_page', 'pages.graphs_page'):
        importlib.import_module(module_name)


_register_pages()

app.add_static_files('/static', STATIC_DIR)

_background_sync_task: asyncio.Task | None = None


def _start_background_sync() -> None:
    global _background_sync_task
    install_connection_reset_filter()
    if _background_sync_task is None or _background_sync_task.done():
        _background_sync_task = asyncio.create_task(background_sync_loop())


app.on_startup(_start_background_sync)


@app.get('/api/devices')
def devices_status() -> JSONResponse:
    return JSONResponse({'ok': True, 'active': active_devices(), 'failures': probe_failures()})


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

    device_id = str(row.get('id') or row.get('device_id') or '').strip().lower()
    if not device_id.startswith('ecosensor'):
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

    inserted = await asyncio.to_thread(save_measurement, host, row)
    return JSONResponse({
        'ok': True,
        'inserted': inserted,
        'device_id': device_id,
        'measurement_id': row.get('measurement_id'),
    })


@app.get('/api/measurements.csv')
def download_measurements_csv(device_id: str | None = Query(default=None)) -> Response:
    filename_id = (device_id or 'ecosensor01').strip() or 'ecosensor01'
    return Response(
        content=measurements_csv_text(device_id),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename_id}_mediciones.csv"'},
    )


@app.get('/api/graph_read')
def graph_read(
    op: str = Query(default='history'),
    id: int = Query(default=0),
    limit: int = Query(default=5000),
    device_id: str | None = Query(default=None),
) -> JSONResponse:
    if op == 'latest':
        return JSONResponse({'ok': True, 'row': graph_latest_row(device_id)})
    if op == 'history':
        return JSONResponse({'ok': True, 'rows': graph_rows_history(limit, device_id)})
    if op == 'since':
        return JSONResponse({'ok': True, 'rows': graph_rows_since(id, limit, device_id)})
    return JSONResponse({'ok': False, 'error': 'unknown_op', 'allowed': 'latest|history|since'}, status_code=400)


start_mdns_service()

ui.run(host=UI_HOST, port=UI_PORT, title='EcoSensor Servidor', reload=False, storage_secret='ecosensor-servidor-local')
