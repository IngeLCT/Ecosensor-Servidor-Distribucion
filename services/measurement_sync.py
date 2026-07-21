import asyncio
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from config import DEVICE_ID
from services.device_registry import (
    device_id_from_host,
    ensure_active_devices,
    ensure_device_active,
    host_for_device,
    invalidate_device_status,
    mark_device_seen,
    normalize_device_id,
    recently_seen_devices,
    refresh_active_devices,
)
from services.esp_client import build_endpoints, configure_push_host, delete_json, fetch_json, fetch_readings_export, fetch_readings_range, sync_time_if_needed
from services.history_reset_state import begin_history_reset, finish_history_reset, history_reset_in_progress
from shared.formatters import row_from_payload
from shared.time_utils import parse_timestamp, server_local_now
from storage.measurements_store import (
    get_latest_measurement,
    clear_measurements,
    latest_source_id,
    missing_source_id_ranges,
    repair_historical_invalid_timestamps,
    save_measurement,
    save_measurements_bulk,
    validate_measurements_for_csv,
)

_sync_locks: dict[str, asyncio.Lock] = {}
_synced_notice_printed: set[str] = set()
_history_syncing_devices: set[str] = set()
_preventive_sync_tasks: dict[str, asyncio.Task] = {}
_last_preventive_sync_at: dict[str, float] = {}
SYNC_CHUNK_SIZE = 30
SYNC_MIN_CHUNK_SIZE = 30
SYNC_MAX_CHUNK_SIZE = 120
SYNC_CHUNK_STEP = 30
SYNC_FAST_BATCH_SECONDS = 8.0
SYNC_SLOW_BATCH_SECONDS = 24.0
SYNC_PREVENTIVE_MIN_INTERVAL_SECONDS = 90.0
SYNC_MAX_BATCHES_PER_CYCLE = 300
SYNC_PROGRESS_INTERVAL_SECONDS = 60.0
SYNC_STREAM_CHUNK_SIZE = 1000
SYNC_STREAM_TIMEOUT_SECONDS = 75.0
SYNC_STREAM_MAX_RETRIES = 1
SYNC_BLOCK_RETRY_DELAY_SECONDS = 10.0
SYNC_BLOCK_MAX_RETRIES = 1
PUSH_HOST_GRACE_SECONDS = 120
DEFAULT_MEASUREMENT_WINDOW_SECONDS = 300
BACKGROUND_SYNC_FRESH_DEVICE_SECONDS = 75


def summarize_response(response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    return {
        'ok': response.get('ok'),
        'status': response.get('status'),
        'url': response.get('url'),
    }


def record_sync_event(device_id: str, event: str, **details: Any) -> dict[str, Any]:
    return {'device_id': device_id, 'event': event, **details}


def is_history_syncing(device_id: str | None = None) -> bool:
    if device_id:
        return device_id in _history_syncing_devices
    return bool(_history_syncing_devices)


def cancel_device_sync(device_id: str) -> None:
    task = _preventive_sync_tasks.pop(device_id, None)
    if task is not None and not task.done():
        task.cancel()
    _history_syncing_devices.discard(device_id)
    _synced_notice_printed.discard(device_id)
    _last_preventive_sync_at.pop(device_id, None)


def _lock_for(device_id: str) -> asyncio.Lock:
    if device_id not in _sync_locks:
        _sync_locks[device_id] = asyncio.Lock()
    return _sync_locks[device_id]


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
    return bool(value)


def _enrich_time_metadata(item: dict[str, Any], current_uptime_s: Any, server_now: datetime, current_boot_id: Any = None) -> None:
    parsed_time_valid = _bool_or_none(item.get('time_valid'))
    time_valid = bool(parsed_time_valid) or (parsed_time_valid is None and bool(item.get('timestamp')))
    item['time_valid'] = time_valid
    item['time_source'] = item.get('time_source') or ('esp' if time_valid else 'uptime')
    if time_valid and parse_timestamp(item.get('timestamp')) is None:
        item['time_valid'] = False
        item['time_source'] = 'invalid_timestamp'


def _apply_status_latest_timestamp(item: dict[str, Any], status_data: Any) -> bool:
    """Usa /status como fuente de hora para la última medición antes de estimar.

    En firmwares anteriores, /lecturas puede llegar sin timestamp confiable y el
    servidor termina estimando con la hora local del PC. /status, en cambio,
    reporta last_measurement_timestamp para la misma última medición guardada.
    """
    if not isinstance(status_data, dict):
        return False
    status_timestamp = str(status_data.get('last_measurement_timestamp') or '').strip()
    if not status_timestamp:
        return False
    if _bool_or_none(status_data.get('last_measurement_time_valid')) is False:
        return False

    try:
        item_id = int(item.get('measurement_id') or item.get('id') or 0)
    except (TypeError, ValueError):
        item_id = 0
    try:
        status_id = int(status_data.get('last_measurement_id') or 0)
    except (TypeError, ValueError):
        status_id = 0
    if item_id > 0 and status_id > 0 and item_id != status_id:
        return False

    current_source = str(item.get('time_source') or '').lower()
    current_timestamp = str(item.get('timestamp') or '').strip()
    should_replace = not current_timestamp or current_source.startswith('estimated') or current_source in {'pending_estimate', 'invalid_history_time'}
    if not should_replace:
        return False

    item['timestamp'] = status_timestamp
    item['time_valid'] = True
    item['time_source'] = 'esp_live'
    if status_data.get('boot_id') is not None and item.get('boot_id') is None:
        item['boot_id'] = status_data.get('boot_id')
    if status_data.get('last_measurement_uptime_s') is not None and item.get('uptime_s') is None:
        item['uptime_s'] = status_data.get('last_measurement_uptime_s')
    return True



def _parse_dt(value: Any) -> datetime | None:
    return parse_timestamp(value)


def _push_overdue(row: dict[str, Any] | None) -> tuple[bool, int, int]:
    if not row:
        return False, 0, DEFAULT_MEASUREMENT_WINDOW_SECONDS
    last_seen = _parse_dt(row.get('received_at')) or _parse_dt(row.get('timestamp'))
    if not last_seen:
        return False, 0, DEFAULT_MEASUREMENT_WINDOW_SECONDS
    try:
        window_s = int(row.get('window_s') or DEFAULT_MEASUREMENT_WINDOW_SECONDS)
    except (TypeError, ValueError):
        window_s = DEFAULT_MEASUREMENT_WINDOW_SECONDS
    window_s = max(60, window_s)
    age_s = int((server_local_now() - last_seen).total_seconds())
    return age_s > window_s + PUSH_HOST_GRACE_SECONDS, age_s, window_s


def _status_is_active_for_push(status_data: Any) -> bool:
    if not isinstance(status_data, dict):
        return False
    if status_data.get('can_push') is True:
        return True
    wifi = str(status_data.get('wifi') or '').strip().lower()
    sensors = str(status_data.get('sensors') or '').strip().lower()
    return wifi == 'connected' and sensors == 'running'


async def _configure_push_host_if_overdue(device_id: str, host: str, row: dict[str, Any] | None, status_data: Any) -> None:
    overdue, age_s, window_s = _push_overdue(row)
    if not overdue or not _status_is_active_for_push(status_data):
        return

    current_push_host = str((status_data or {}).get('push_host') or '').strip() if isinstance(status_data, dict) else ''
    result = await configure_push_host(host, timeout=3.0)
    record_sync_event(
        device_id,
        'configure_push_host',
        host=host,
        ok=bool(result.get('ok')),
        age_s=age_s,
        window_s=window_s,
        previous_push_host=current_push_host or None,
        push_host=result.get('push_host'),
        response=summarize_response(result.get('sync')),
    )
    if result.get('ok'):
        confirm = result.get('status') if isinstance(result.get('status'), dict) else {}
        confirm_data = confirm.get('data') if isinstance(confirm.get('data'), dict) else {}
        reported_push_host = confirm_data.get('push_host') if isinstance(confirm_data, dict) else None
        can_push = confirm_data.get('can_push') if isinstance(confirm_data, dict) else None
        wifi = confirm_data.get('wifi') if isinstance(confirm_data, dict) else None
        print(
            f"[measurement_sync] {device_id}: push sin recibir hace {age_s}s; "
            f"push_host enviado={result.get('push_host')}; "
            f"reportado={reported_push_host}; wifi={wifi}; can_push={can_push}",
            flush=True,
        )


def display_host(host: str) -> str:
    clean = (host or DEVICE_ID).strip()
    if clean.endswith('.local'):
        clean = clean[:-6]
    return clean or DEVICE_ID


def _format_duration(seconds: float | int | None) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}h{minutes:02d}m{secs:02d}s'
    if minutes:
        return f'{minutes}m{secs:02d}s'
    return f'{secs}s'


def _sync_speed_eta(total_received: int, pending_count: int, started_at: float) -> tuple[float, str]:
    elapsed = max(0.001, monotonic() - started_at)
    speed = total_received / elapsed if total_received > 0 else 0.0
    remaining = max(0, pending_count - total_received)
    eta = remaining / speed if speed > 0 else 0
    return speed, _format_duration(eta)


async def _save_remote_rows(
    host: str,
    device_id: str,
    rows: list[Any],
    current_uptime_s: Any,
    current_boot_id: Any,
) -> tuple[int, int, int]:
    """Guarda filas remotas y devuelve (insertadas, min_source_id, max_source_id)."""
    if history_reset_in_progress(device_id):
        return 0, 0, 0
    inserted_count = 0
    min_seen_source_id = 0
    max_seen_source_id = 0
    server_now = server_local_now()
    prepared_rows: list[dict[str, Any]] = []

    for item in rows:
        if not isinstance(item, dict):
            continue
        source_id = item.get('measurement_id') or item.get('id')
        try:
            source_id_int = int(source_id or 0)
        except (TypeError, ValueError):
            source_id_int = 0
        if source_id_int > 0:
            min_seen_source_id = source_id_int if min_seen_source_id == 0 else min(min_seen_source_id, source_id_int)
            max_seen_source_id = max(max_seen_source_id, source_id_int)

        item['device_id'] = device_id
        item['id'] = device_id
        item['measurement_id'] = source_id

        historical_row = source_id_int > 0
        historical_time_valid = _bool_or_none(item.get('time_valid'))
        if historical_row and not historical_time_valid:
            # En histórico no estimamos con la hora actual del servidor. Estas
            # filas se reconstruyen después por source_id usando la siguiente
            # medición válida como ancla.
            item['time_valid'] = False
            item['time_source'] = item.get('time_source') or 'invalid_history_time'
        else:
            _enrich_time_metadata(item, current_uptime_s, server_now, current_boot_id)

        if not item.get('timestamp'):
            item['time_valid'] = False
            item['time_source'] = item.get('time_source') or 'uptime'
        prepared_rows.append(item)

    if prepared_rows:
        inserted_count = await asyncio.to_thread(save_measurements_bulk, host, prepared_rows, device_id)

    return inserted_count, min_seen_source_id, max_seen_source_id


async def sync_sensor_measurements(
    device_id: str | None = None,
    *,
    fetch_latest: bool = True,
    sync_history: bool = True,
    user_initiated: bool = False,
) -> dict[str, Any] | None:
    """Sincroniza un EcoSensor concreto y devuelve su última medición conocida.

    Cuando ``fetch_latest`` es False no consulta ``/lecturas``. Cuando
    ``sync_history`` es False solo deja listo el estado rápido del sensor
    (vida/hora/última medición) y no recupera histórico desde SD.

    ``user_initiated`` mantiene la estrategia conservadora de lotes, pero evita
    esperas largas entre reintentos cuando el usuario pidió la sincronización
    manualmente antes de descargar CSV.
    """
    target_id = normalize_device_id(device_id, default=DEVICE_ID) or DEVICE_ID
    if history_reset_in_progress(target_id):
        return await asyncio.to_thread(get_latest_measurement, target_id)
    active = await ensure_device_active(device_id)
    if not active:
        target_id = (device_id or DEVICE_ID).strip().lower() or DEVICE_ID
        record_sync_event(target_id, 'inactive', reason='no_active_device')
        return await asyncio.to_thread(get_latest_measurement, target_id)

    selected_device_id = str(active['device_id'])
    host_now = str(active['host'])
    initial_row = await asyncio.to_thread(get_latest_measurement, selected_device_id)

    async with _lock_for(selected_device_id):
        if history_reset_in_progress(selected_device_id):
            return await asyncio.to_thread(get_latest_measurement, selected_device_id)
        record_sync_event(
            selected_device_id,
            'start',
            host=host_now,
            last_seen=active.get('last_seen'),
            status_time_valid=(active.get('status') or {}).get('time_valid'),
            status_needs_time_sync=(active.get('status') or {}).get('needs_time_sync'),
        )

        # La sincronización de hora es útil, pero no debe bloquear la lectura de
        # mediciones: el ESP32 puede estar activo y con datos aunque /time falle.
        connection = await sync_time_if_needed(host_now, timeout=2.0)
        record_sync_event(
            selected_device_id,
            'time_sync',
            host=host_now,
            ok=bool(connection.get('ok')),
            synced=bool(connection.get('synced')),
            time_drift_s=connection.get('time_drift_s'),
            forced_by_time_drift=connection.get('forced_by_time_drift'),
            status=summarize_response(connection.get('status')),
            sync=summarize_response(connection.get('sync')) if connection.get('sync') else None,
        )
        if connection.get('ok'):
            host_now = str(connection.get('host') or host_now)

        status_payload = connection.get('status') if isinstance(connection.get('status'), dict) else {}
        status_data = status_payload.get('data') if isinstance(status_payload.get('data'), dict) else {}
        if not status_data and isinstance(active.get('status'), dict):
            # Al arrancar, /time o /status pueden fallar puntualmente mientras el
            # ESP32 está ocupado. El registro activo suele conservar el último
            # /status válido; usarlo evita esperar al siguiente push para saber
            # que hay histórico en SD.
            status_data = active.get('status') or {}
        await _configure_push_host_if_overdue(selected_device_id, host_now, initial_row, status_data)

        endpoints_now = build_endpoints(host_now)
        row = None
        total_inserted = 0
        total_received = 0
        historical_repaired = 0
        batches = 0
        sync_started_printed = False
        suppress_zero_sync_log = False
        last_progress_print = monotonic()
        history_started_at = monotonic()
        block_retry_delay_seconds = 2.0 if user_initiated else SYNC_BLOCK_RETRY_DELAY_SECONDS
        current_chunk_size = SYNC_CHUNK_SIZE

        if endpoints_now['lecturas']:
            completed_history_sync = False
            local_floor_id = await asyncio.to_thread(latest_source_id, selected_device_id)

            latest_inserted = False
            latest_remote_id = 0
            latest_remote_id_known = False
            latest_valid = False

            if fetch_latest:
                # Prioridad 1: pedir primero la última medición. Esto mantiene
                # compatibilidad con pantallas/flujos que aún no dependen solo
                # del push del ESP32.
                lecturas = await fetch_json(endpoints_now['lecturas'], timeout=3.0)
                data = lecturas.get('data') if lecturas.get('ok') else None
                if isinstance(data, dict) and data.get('valid'):
                    row = row_from_payload(data)
                    if row:
                        row['device_id'] = selected_device_id
                        row['id'] = selected_device_id
                        _apply_status_latest_timestamp(row, status_data)
                        _enrich_time_metadata(row, data.get('current_uptime_s'), server_local_now(), data.get('boot_id'))
                        if row.get('time_source') == 'esp':
                            row['time_source'] = 'esp_live'
                        try:
                            latest_remote_id = int(row.get('measurement_id') or 0)
                        except (TypeError, ValueError):
                            latest_remote_id = 0
                        latest_remote_id_known = latest_remote_id > 0
                        latest_inserted = await asyncio.to_thread(save_measurement, host_now, row)
                latest_valid = bool(isinstance(data, dict) and data.get('valid'))
                if endpoints_now.get('status'):
                    fresh_status = await fetch_json(endpoints_now['status'], timeout=4.0)
                    fresh_data = fresh_status.get('data') if fresh_status.get('ok') else None
                    if isinstance(fresh_data, dict):
                        status_data = fresh_data
                response_summary = summarize_response(lecturas)
            else:
                status_data = active.get('status') if isinstance(active.get('status'), dict) else {}
                response_summary = 'skipped_fetch_latest'

            # El límite histórico real es exclusivamente sd_last_id de un
            # /status fresco. last_measurement_id o el último push pueden ser
            # mayores, estar cacheados o pertenecer a un historial borrado.
            try:
                latest_remote_id = max(0, int(status_data.get('sd_last_id') or 0))
                latest_remote_id_known = True
            except (TypeError, ValueError, AttributeError):
                latest_remote_id = 0
                latest_remote_id_known = False

            record_sync_event(
                selected_device_id,
                'fetch_latest',
                host=host_now,
                ok=True,
                valid=latest_valid,
                inserted=latest_inserted,
                local_floor_id=local_floor_id,
                latest_remote_id=latest_remote_id,
                response=response_summary,
            )

            if latest_inserted:
                total_inserted += 1

            if not sync_history:
                missing_ranges = []
                pending_count = 0
                completed_history_sync = True
                record_sync_event(
                    selected_device_id,
                    'fetch_history_skipped',
                    host=host_now,
                    reason='quick_sync_only',
                    latest_remote_id=latest_remote_id,
                )
            else:
                missing_ranges = await asyncio.to_thread(missing_source_id_ranges, selected_device_id, latest_remote_id)
                pending_count = sum((end_id - start_id + 1) for start_id, end_id in missing_ranges)

            if latest_remote_id > 0:
                if missing_ranges:
                    _synced_notice_printed.discard(selected_device_id)
                    ranges_preview = ','.join(
                        f"{start_id}-{end_id}" if start_id != end_id else str(start_id)
                        for start_id, end_id in missing_ranges[-4:]
                    )
                    print(
                        f"[measurement_sync] inicio sincronizacion {selected_device_id}: "
                        f"{pending_count} datos por sincronizar; rangos={ranges_preview}",
                        flush=True,
                    )
                    sync_started_printed = True
                else:
                    suppress_zero_sync_log = True
                    if sync_history and selected_device_id not in _synced_notice_printed:
                        print(
                            f"[measurement_sync] {selected_device_id}: sincronizado; 0 datos pendientes",
                            flush=True,
                        )
                        _synced_notice_printed.add(selected_device_id)
            else:
                suppress_zero_sync_log = True
                if sync_history and selected_device_id not in _synced_notice_printed:
                    if latest_remote_id_known:
                        print(
                            f"[measurement_sync] {selected_device_id}: sincronizado; sin ID remoto pendiente",
                            flush=True,
                        )
                        _synced_notice_printed.add(selected_device_id)
                    else:
                        print(
                            f"[measurement_sync] {selected_device_id}: no se pudo confirmar ID remoto; reintentara sincronizacion automatica",
                            flush=True,
                        )

            # Recuperación de histórico por rangos faltantes concretos.
            # Se recorre de IDs altos a bajos para rellenar primero lo más reciente.
            if missing_ranges:
                _history_syncing_devices.add(selected_device_id)
                for range_start, range_end in reversed(missing_ranges):
                    stream_to = range_end
                    while stream_to >= range_start and batches < SYNC_MAX_BATCHES_PER_CYCLE:
                        stream_from = max(range_start, stream_to - SYNC_STREAM_CHUNK_SIZE + 1)
                        export_started_at = monotonic()
                        export = await fetch_readings_export(
                            host_now,
                            from_id=stream_from,
                            to_id=stream_to,
                            timeout=SYNC_STREAM_TIMEOUT_SECONDS,
                        )
                        export_data = export.get('data') if isinstance(export.get('data'), dict) else None
                        export_rows = export_data.get('rows') if isinstance(export_data, dict) else None
                        export_rows = export_rows if isinstance(export_rows, list) else []
                        if not export.get('ok') and not export_rows:
                            for retry in range(1, SYNC_STREAM_MAX_RETRIES + 1):
                                print(
                                    f"[measurement_sync] {selected_device_id}: stream sin progreso "
                                    f"range={stream_from}-{stream_to} response={summarize_response(export)}; "
                                    f"reintentando mismo bloque ({retry}/{SYNC_STREAM_MAX_RETRIES})",
                                    flush=True,
                                )
                                export = await fetch_readings_export(
                                    host_now,
                                    from_id=stream_from,
                                    to_id=stream_to,
                                    timeout=SYNC_STREAM_TIMEOUT_SECONDS,
                                )
                                export_data = export.get('data') if isinstance(export.get('data'), dict) else None
                                export_rows = export_data.get('rows') if isinstance(export_data, dict) else None
                                export_rows = export_rows if isinstance(export_rows, list) else []
                                if export.get('ok') or export_rows:
                                    break
                        export_inserted = 0
                        export_min_seen = 0
                        export_max_seen = 0
                        if export_rows:
                            export_inserted, export_min_seen, export_max_seen = await _save_remote_rows(
                                host_now,
                                selected_device_id,
                                export_rows,
                                None,
                                None,
                            )
                            total_inserted += export_inserted
                            total_received += len(export_rows)
                            if export_inserted > 0 and export_min_seen > 0 and export_max_seen > 0:
                                historical_repaired += await asyncio.to_thread(
                                    repair_historical_invalid_timestamps,
                                    selected_device_id,
                                    export_min_seen,
                                    export_max_seen,
                                )
                        batches += 1
                        export_ok = bool(export.get('ok')) and bool(export_rows)
                        record_sync_event(
                            selected_device_id,
                            'fetch_export_range',
                            host=host_now,
                            batch=batches,
                            from_id=stream_from,
                            to_id=stream_to,
                            ok=bool(export.get('ok')),
                            rows=len(export_rows),
                            inserted=export_inserted,
                            elapsed_s=round(monotonic() - export_started_at, 2),
                            response=summarize_response(export),
                        )
                        now_progress = monotonic()
                        if pending_count > 0 and (export_rows or now_progress - last_progress_print >= SYNC_PROGRESS_INTERVAL_SECONDS):
                            synced_so_far = min(total_received, pending_count)
                            remaining = max(0, pending_count - synced_so_far)
                            speed, eta = _sync_speed_eta(synced_so_far, pending_count, history_started_at)
                            print(
                                f"[measurement_sync] progreso {selected_device_id}: "
                                f"{synced_so_far}/{pending_count} recibidos, "
                                f"{total_inserted} insertados, faltan {remaining}, "
                                f"velocidad={speed:.1f} filas/s, eta={eta}, "
                                f"modo=stream, rango={stream_from}-{stream_to}",
                                flush=True,
                            )
                            last_progress_print = now_progress
                        if export_ok:
                            stream_to = stream_from - 1
                            continue

                        print(
                            f"[measurement_sync] {selected_device_id}: stream sin progreso "
                            f"range={stream_from}-{stream_to} response={summarize_response(export)}; "
                            f"usando fallback por lotes",
                            flush=True,
                        )
                        chunk_to = stream_to
                        while chunk_to >= stream_from and batches < SYNC_MAX_BATCHES_PER_CYCLE:
                            chunk_from = max(stream_from, chunk_to - current_chunk_size + 1)
                            batch_started_at = monotonic()
                            missing = await fetch_readings_range(
                                host_now,
                                from_id=chunk_from,
                                to_id=chunk_to,
                                limit=current_chunk_size,
                                timeout=30.0,
                            )
                            missing_data = missing.get('data') if isinstance(missing.get('data'), dict) else None
                            rows = missing_data.get('rows') if isinstance(missing_data, dict) else None
                            rows = rows if isinstance(rows, list) else []
                            inserted_count = 0
                            min_seen_source_id = 0
                            max_seen_source_id = 0
                            if rows:
                                inserted_count, min_seen_source_id, max_seen_source_id = await _save_remote_rows(
                                    host_now,
                                    selected_device_id,
                                    rows,
                                    missing_data.get('current_uptime_s') if isinstance(missing_data, dict) else None,
                                    missing_data.get('boot_id') if isinstance(missing_data, dict) else None,
                                )
                                total_inserted += inserted_count
                                total_received += len(rows)
                                if inserted_count > 0 and min_seen_source_id > 0 and max_seen_source_id > 0:
                                    historical_repaired += await asyncio.to_thread(
                                        repair_historical_invalid_timestamps,
                                        selected_device_id,
                                        min_seen_source_id,
                                        max_seen_source_id,
                                    )
    
                            batches += 1
                            ok = bool(missing.get('ok'))
                            record_sync_event(
                                selected_device_id,
                                'fetch_range_batch',
                                host=host_now,
                                batch=batches,
                                from_id=chunk_from,
                                to_id=chunk_to,
                                limit=current_chunk_size,
                                ok=ok,
                                rows=len(rows),
                                inserted=inserted_count,
                                min_seen_source_id=min_seen_source_id,
                                max_seen_source_id=max_seen_source_id,
                                response=summarize_response(missing),
                            )
    
                            batch_elapsed = monotonic() - batch_started_at
                            next_chunk_size = current_chunk_size
                            if ok and len(rows) >= current_chunk_size and batch_elapsed <= SYNC_FAST_BATCH_SECONDS:
                                next_chunk_size = min(SYNC_MAX_CHUNK_SIZE, current_chunk_size + SYNC_CHUNK_STEP)
                            elif (not ok and not rows) or batch_elapsed >= SYNC_SLOW_BATCH_SECONDS:
                                next_chunk_size = max(SYNC_MIN_CHUNK_SIZE, current_chunk_size - SYNC_CHUNK_STEP)
    
                            now_progress = monotonic()
                            if pending_count > 0 and now_progress - last_progress_print >= SYNC_PROGRESS_INTERVAL_SECONDS:
                                synced_so_far = min(total_received, pending_count)
                                remaining = max(0, pending_count - synced_so_far)
                                speed, eta = _sync_speed_eta(synced_so_far, pending_count, history_started_at)
                                print(
                                    f"[measurement_sync] progreso {selected_device_id}: "
                                    f"{synced_so_far}/{pending_count} recibidos, "
                                    f"{total_inserted} insertados, faltan {remaining}, "
                                    f"velocidad={speed:.1f} filas/s, eta={eta}, "
                                    f"lotes={batches}, lote_actual={current_chunk_size}, ultimo_rango={chunk_from}-{chunk_to}",
                                    flush=True,
                                )
                                last_progress_print = now_progress
    
                            if not ok and not rows:
                                retry_success = False
                                for retry in range(1, SYNC_BLOCK_MAX_RETRIES + 1):
                                    print(
                                        f"[measurement_sync] {selected_device_id}: bloque sin progreso "
                                        f"range={chunk_from}-{chunk_to} response={summarize_response(missing)}; "
                                        f"reintentando en {int(block_retry_delay_seconds)}s "
                                        f"({retry}/{SYNC_BLOCK_MAX_RETRIES})",
                                        flush=True,
                                    )
                                    await asyncio.sleep(block_retry_delay_seconds)
                                    missing = await fetch_readings_range(
                                        host_now,
                                        from_id=chunk_from,
                                        to_id=chunk_to,
                                        limit=current_chunk_size,
                                        timeout=30.0,
                                    )
                                    missing_data = missing.get('data') if isinstance(missing.get('data'), dict) else None
                                    rows = missing_data.get('rows') if isinstance(missing_data, dict) else None
                                    rows = rows if isinstance(rows, list) else []
                                    ok = bool(missing.get('ok'))
                                    if rows:
                                        inserted_count, min_seen_source_id, max_seen_source_id = await _save_remote_rows(
                                            host_now,
                                            selected_device_id,
                                            rows,
                                            missing_data.get('current_uptime_s') if isinstance(missing_data, dict) else None,
                                            missing_data.get('boot_id') if isinstance(missing_data, dict) else None,
                                        )
                                        total_inserted += inserted_count
                                        total_received += len(rows)
                                        if inserted_count > 0 and min_seen_source_id > 0 and max_seen_source_id > 0:
                                            historical_repaired += await asyncio.to_thread(
                                                repair_historical_invalid_timestamps,
                                                selected_device_id,
                                                min_seen_source_id,
                                                max_seen_source_id,
                                            )
                                        retry_success = True
                                        break
                                if not retry_success and not ok and not rows:
                                    print(
                                        f"[measurement_sync] {selected_device_id}: bloque sin progreso definitivo "
                                        f"range={chunk_from}-{chunk_to} response={summarize_response(missing)}",
                                        flush=True,
                                    )
                                    break
                            current_chunk_size = next_chunk_size
                            chunk_to = chunk_from - 1
    
                        stream_to = stream_from - 1

                    if batches >= SYNC_MAX_BATCHES_PER_CYCLE:
                        break

                completed_history_sync = batches < SYNC_MAX_BATCHES_PER_CYCLE
                if completed_history_sync:
                    full_repaired = await asyncio.to_thread(repair_historical_invalid_timestamps, selected_device_id)
                    if full_repaired:
                        historical_repaired += full_repaired
                if historical_repaired:
                    print(
                        f"[measurement_sync] {selected_device_id}: fechas historicas reparadas: {historical_repaired}",
                        flush=True,
                    )
                _history_syncing_devices.discard(selected_device_id)
                record_sync_event(
                    selected_device_id,
                    'fetch_range_summary',
                    host=host_now,
                    batches=batches,
                    chunk_size=current_chunk_size,
                    rows=total_received,
                    inserted=total_inserted,
                    complete=completed_history_sync,
                    ranges=len(missing_ranges),
                    pending=pending_count,
                    latest_remote_id=latest_remote_id,
                )
            else:
                completed_history_sync = True
                record_sync_event(
                    selected_device_id,
                    'fetch_history_skipped',
                    host=host_now,
                    reason='no_missing_ranges',
                    latest_remote_id=latest_remote_id,
                )

        if not sync_started_printed:
            print(f"[measurement_sync] inicio sincronizacion {selected_device_id}", flush=True)

        if not row:
            row = await asyncio.to_thread(get_latest_measurement, selected_device_id)

        if not suppress_zero_sync_log:
            if sync_history and sync_started_printed:
                final_remaining = max(0, pending_count - min(total_received, pending_count)) if 'pending_count' in locals() else 0
                if final_remaining > 0:
                    print(
                        f"[measurement_sync] fin sincronizacion {selected_device_id}: "
                        f"{total_inserted} datos sincronizados; faltan {final_remaining}",
                        flush=True,
                    )
                else:
                    print(
                        f"[measurement_sync] fin sincronizacion {selected_device_id}: "
                        f"{total_inserted} datos sincronizados",
                        flush=True,
                    )
            else:
                print(
                    f"[measurement_sync] fin sincronizacion {selected_device_id}: "
                    f"{total_inserted} datos sincronizados",
                    flush=True,
                )

        record_sync_event(
            selected_device_id,
            'done',
            host=host_now,
            latest_timestamp=(row or {}).get('timestamp'),
            latest_received_at=(row or {}).get('received_at'),
            latest_measurement_id=(row or {}).get('measurement_id'),
            latest_time_valid=(row or {}).get('time_valid'),
            latest_time_source=(row or {}).get('time_source'),
        )
        return row


async def coordinated_clear_history(device_id: str) -> dict[str, Any]:
    target_id = normalize_device_id(device_id)
    if not target_id:
        return {'ok': False, 'error': 'invalid_device_id'}
    active = await ensure_device_active(target_id)
    if not active:
        return {'ok': False, 'error': 'sensor_not_active'}
    host = str(active.get('host') or host_for_device(target_id))
    begin_history_reset(target_id)
    cancel_device_sync(target_id)
    confirmed = False
    try:
        async with _lock_for(target_id):
            invalidate_device_status(target_id)
            remote = await delete_json(build_endpoints(host)['readings_clear'], timeout=15.0)
            if not remote.get('ok'):
                return {'ok': False, 'error': 'remote_clear_failed', 'remote': summarize_response(remote)}
            fresh = await fetch_json(build_endpoints(host)['status'], timeout=8.0)
            status = fresh.get('data') if fresh.get('ok') and isinstance(fresh.get('data'), dict) else None
            if not isinstance(status, dict):
                return {'ok': False, 'error': 'fresh_status_failed', 'status': summarize_response(fresh)}
            expected = {
                'sd_ready': status.get('sd_ready') is True,
                'sd_last_id': int(status.get('sd_last_id') or 0) == 0,
                'last_measurement_id': int(status.get('last_measurement_id') or 0) == 0,
                'checkpoint_valid': status.get('checkpoint_valid') is True,
                'checkpoint_current': status.get('checkpoint_current') is True,
                'history_index_ready': status.get('history_index_ready') is True,
                'history_index_points': int(status.get('history_index_points') or 0) == 0,
            }
            if not all(expected.values()):
                return {'ok': False, 'error': 'remote_clear_not_confirmed', 'checks': expected, 'status': status}
            deleted = await asyncio.to_thread(clear_measurements, target_id)
            cancel_device_sync(target_id)
            invalidate_device_status(target_id)
            mark_device_seen(target_id, host, status)
            confirmed = True
            return {'ok': True, 'device_id': target_id, 'deleted': deleted, 'status': status}
    finally:
        finish_history_reset(target_id, confirmed=confirmed)


async def sync_before_csv_download(device_id: str | None = None) -> dict[str, Any]:
    """Sincroniza histórico bajo demanda antes de permitir descargar CSV."""
    target_id = normalize_device_id(device_id, default=DEVICE_ID)
    if not target_id:
        return {
            'ok': False,
            'device_id': str(device_id or '').strip(),
            'status_code': 400,
            'error': 'invalid_device_id',
            'message': 'device_id inválido. Usa ecosensor01 a ecosensor12.',
        }

    active = await ensure_device_active(target_id)
    if not active:
        return {
            'ok': False,
            'device_id': target_id,
            'status_code': 409,
            'error': 'sensor_not_active',
            'message': 'No se encontró activo el EcoSensor seleccionado; no se descargó el CSV.',
        }

    try:
        row = await sync_sensor_measurements(
            target_id,
            fetch_latest=True,
            sync_history=True,
            user_initiated=True,
        )
    except Exception as exc:
        return {
            'ok': False,
            'device_id': target_id,
            'error': f'sync_failed: {exc}',
            'message': 'No se pudo sincronizar el historial antes de descargar el CSV.',
        }

    host = str(active.get('host') or host_for_device(target_id))
    fresh_status = await fetch_json(build_endpoints(host)['status'], timeout=5.0)
    fresh_data = fresh_status.get('data') if fresh_status.get('ok') and isinstance(fresh_status.get('data'), dict) else None
    if not isinstance(fresh_data, dict):
        return {
            'ok': False,
            'device_id': target_id,
            'error': 'fresh_status_failed',
            'message': 'No se pudo confirmar sd_last_id con un /status fresco.',
        }
    try:
        latest_remote_id = max(0, int(fresh_data.get('sd_last_id') or 0))
    except (TypeError, ValueError):
        latest_remote_id = 0

    missing_ranges = await asyncio.to_thread(missing_source_id_ranges, target_id, latest_remote_id)
    pending_count = sum((end_id - start_id + 1) for start_id, end_id in missing_ranges)
    if pending_count > 0:
        return {
            'ok': False,
            'device_id': target_id,
            'pending': pending_count,
            'missing_ranges': missing_ranges,
            'latest_remote_id': latest_remote_id,
            'message': 'Aún existen datos pendientes por sincronizar; no se generó el CSV.',
        }

    validation = await asyncio.to_thread(validate_measurements_for_csv, target_id)
    if not validation.get('ok'):
        return {
            'ok': False,
            'device_id': target_id,
            'pending': 0,
            'latest_remote_id': latest_remote_id,
            'error': 'invalid_timestamps',
            **validation,
        }

    return {
        'ok': True,
        'device_id': target_id,
        'pending': 0,
        'latest_remote_id': latest_remote_id,
        'message': 'Historial sincronizado y fechas validadas. Iniciando descarga CSV.',
    }


def schedule_preventive_history_sync(device_id: str | None, *, delay_seconds: float = 2.0) -> None:
    """Agenda una sincronización histórica preventiva sin bloquear al usuario.

    Se usa tras recibir push o detectar actividad. Evita lanzar trabajos
    repetidos para el mismo EcoSensor y deja que el lock existente serialize
    contra descargas CSV o ciclos automáticos.
    """
    if device_id and history_reset_in_progress(device_id):
        return
    target_id = (device_id or DEVICE_ID).strip().lower() or DEVICE_ID
    if target_id in _history_syncing_devices:
        return
    now = monotonic()
    if now - _last_preventive_sync_at.get(target_id, 0.0) < SYNC_PREVENTIVE_MIN_INTERVAL_SECONDS:
        return
    existing = _preventive_sync_tasks.get(target_id)
    if existing and not existing.done():
        return

    async def _run() -> None:
        try:
            await asyncio.sleep(delay_seconds)
            _last_preventive_sync_at[target_id] = monotonic()
            await sync_sensor_measurements(target_id, fetch_latest=True, sync_history=True)
        except Exception as exc:
            record_sync_event(target_id, 'preventive_sync_error', error=str(exc)[:220])

    _preventive_sync_tasks[target_id] = asyncio.create_task(_run())


async def sync_latest_measurements(device_id: str | None = None) -> dict[str, Any] | None:
    """Compatibilidad: sincroniza el sensor seleccionado o el primer activo."""
    if device_id:
        return await sync_sensor_measurements(device_id)
    devices = await ensure_active_devices()
    selected = devices[0]['device_id'] if devices else DEVICE_ID
    return await sync_sensor_measurements(selected)


async def sync_all_active_measurements() -> list[dict[str, Any] | None]:
    """Sincroniza solo EcoSensores confirmados en el refresco reciente.

    La lista activa puede conservar sensores por TTL para que la UI no parpadee
    ante un fallo puntual de mDNS, pero el loop automático no debe seguir
    consultando sensores desconectados o no confirmados en el ciclo actual.
    """
    await refresh_active_devices()
    devices = recently_seen_devices(BACKGROUND_SYNC_FRESH_DEVICE_SECONDS)
    if not devices:
        return []
    return await asyncio.gather(
        *(sync_sensor_measurements(str(item['device_id'])) for item in devices),
        return_exceptions=False,
    )


async def background_sync_loop(interval_seconds: float = 60.0) -> None:
    print(
        f"[measurement_sync] backend iniciado: sincronizacion automatica cada {interval_seconds:.0f}s",
        flush=True,
    )
    while True:
        try:
            await sync_all_active_measurements()
        except Exception as exc:
            record_sync_event('background', 'loop_error', error=str(exc)[:220])
            # El loop debe sobrevivir caídas puntuales de red/ESP32.
            pass
        await asyncio.sleep(interval_seconds)
