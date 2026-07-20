import csv
import io
import shutil
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from config import DATA_DIR, MEASUREMENTS_DB_FILE
from shared.time_utils import iso_utc, parse_timestamp, to_server_local, to_utc, utc_now_iso, visible_date_time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    host TEXT NOT NULL,
    device_timestamp TEXT,
    received_at TEXT NOT NULL,
    source_id INTEGER,
    boot_id INTEGER,
    uptime_s INTEGER,
    time_valid INTEGER,
    time_source TEXT,
    original_device_timestamp TEXT,
    pm1p0 REAL,
    pm2p5 REAL,
    pm4p0 REAL,
    pm10p0 REAL,
    voc REAL,
    nox REAL,
    co2 REAL,
    temp REAL,
    hum REAL,
    scd_temp REAL,
    scd_hum REAL,
    sen_temp REAL,
    sen_hum REAL,
    gps_valid INTEGER,
    gps_lat REAL,
    gps_lon REAL,
    gps_satellites INTEGER,
    gps_hdop REAL,
    gps_age_ms INTEGER,
    window_s INTEGER
);
'''


def _safe_device_id(device_id: str | None = None) -> str:
    value = str(device_id or 'ecosensor01').strip().lower()
    return ''.join(ch for ch in value if ch.isalnum() or ch in {'_', '-'}) or 'ecosensor01'


def db_file_for_device(device_id: str | None = None):
    """Devuelve el archivo SQLite independiente para un EcoSensor.

    Compatibilidad: el historial existente se conserva como `ecosensor01` usando
    `data/measurements.sqlite3`. Los demás sensores usan un archivo separado.
    """
    safe_id = _safe_device_id(device_id)
    if safe_id == 'ecosensor01':
        return MEASUREMENTS_DB_FILE
    return DATA_DIR / f'measurements_{safe_id}.sqlite3'


def ensure_db(device_id: str | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(measurements)')}
        if 'source_id' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN source_id INTEGER')
        if 'boot_id' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN boot_id INTEGER')
        if 'uptime_s' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN uptime_s INTEGER')
        if 'time_valid' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN time_valid INTEGER')
        if 'time_source' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN time_source TEXT')
        if 'original_device_timestamp' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN original_device_timestamp TEXT')
        if 'scd_temp' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN scd_temp REAL')
        if 'scd_hum' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN scd_hum REAL')
        if 'sen_temp' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN sen_temp REAL')
        if 'sen_hum' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN sen_hum REAL')
        if 'gps_valid' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN gps_valid INTEGER')
        if 'gps_lat' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN gps_lat REAL')
        if 'gps_lon' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN gps_lon REAL')
        if 'gps_satellites' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN gps_satellites INTEGER')
        if 'gps_hdop' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN gps_hdop REAL')
        if 'gps_age_ms' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN gps_age_ms INTEGER')
        conn.execute(
            '''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_measurements_device_timestamp
            ON measurements(device_id, device_timestamp)
            WHERE source_id IS NULL AND device_timestamp IS NOT NULL AND device_timestamp != ''
            '''
        )
        conn.execute(
            '''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_measurements_device_source_id
            ON measurements(device_id, source_id)
            WHERE source_id IS NOT NULL
            '''
        )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_measurements_received_at ON measurements(received_at)')


def clear_measurements(device_id: str | None = None) -> int:
    """Borra el historial local del servidor y reinicia el contador SQLite."""
    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        deleted = conn.execute('DELETE FROM measurements').rowcount
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'measurements'")
        conn.commit()
    return int(deleted or 0)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round2_or_none(value: Any) -> float | None:
    number = _float_or_none(value)
    return None if number is None else round(number, 2)


def _rounded_int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return None if number is None else int(round(number))


def _csv_decimal(value: Any) -> str:
    number = _round2_or_none(value)
    return '' if number is None else f'{number:.2f}'


def _csv_int(value: Any) -> str | int:
    number = _rounded_int_or_none(value)
    return '' if number is None else number


def _bool_or_none(value: Any) -> bool | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
    return bool(value)


def _source_id_from_row(row: dict[str, Any]) -> int | None:
    return _int_or_none(row.get('measurement_id') or row.get('source_id'))


def _measurement_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'id': row['device_id'],
        'host': row['host'],
        'timestamp': row['device_timestamp'],
        'received_at': row['received_at'],
        'measurement_id': row['source_id'],
        'boot_id': row['boot_id'],
        'uptime_s': row['uptime_s'],
        'time_valid': bool(row['time_valid']) if row['time_valid'] is not None else None,
        'time_source': row['time_source'],
        'pm1p0': _round2_or_none(row['pm1p0']),
        'pm2p5': _round2_or_none(row['pm2p5']),
        'pm4p0': _round2_or_none(row['pm4p0']),
        'pm10p0': _round2_or_none(row['pm10p0']),
        'voc': _round2_or_none(row['voc']),
        'nox': _round2_or_none(row['nox']),
        'co2': _rounded_int_or_none(row['co2']),
        'temp': _round2_or_none(row['temp']),
        'hum': _rounded_int_or_none(row['hum']),
        'scd_temp': _round2_or_none(row['scd_temp']) if 'scd_temp' in row.keys() else None,
        'scd_hum': _round2_or_none(row['scd_hum']) if 'scd_hum' in row.keys() else None,
        'sen_temp': _round2_or_none(row['sen_temp']) if 'sen_temp' in row.keys() else None,
        'sen_hum': _round2_or_none(row['sen_hum']) if 'sen_hum' in row.keys() else None,
        'gps_valid': bool(row['gps_valid']) if 'gps_valid' in row.keys() and row['gps_valid'] is not None else None,
        'gps_lat': _float_or_none(row['gps_lat']) if 'gps_lat' in row.keys() else None,
        'gps_lon': _float_or_none(row['gps_lon']) if 'gps_lon' in row.keys() else None,
        'gps_satellites': _int_or_none(row['gps_satellites']) if 'gps_satellites' in row.keys() else None,
        'gps_hdop': _round2_or_none(row['gps_hdop']) if 'gps_hdop' in row.keys() else None,
        'gps_age_ms': _int_or_none(row['gps_age_ms']) if 'gps_age_ms' in row.keys() else None,
        'window_s': row['window_s'],
    }


def get_latest_measurement(device_id: str | None = None) -> dict[str, Any] | None:
    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''
            SELECT device_id, host, device_timestamp, received_at, source_id,
                   boot_id, uptime_s, time_valid, time_source,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum, scd_temp, scd_hum, sen_temp, sen_hum,
                   gps_valid, gps_lat, gps_lon, gps_satellites, gps_hdop, gps_age_ms, window_s
            FROM measurements
            ORDER BY
                CASE WHEN source_id IS NOT NULL THEN 0 ELSE 1 END,
                source_id DESC,
                id DESC,
                received_at DESC
            LIMIT 1
            '''
        ).fetchone()
    return _measurement_row_to_dict(row) if row else None



def latest_source_id(device_id: str = 'ecosensor01') -> int:
    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        value = conn.execute(
            'SELECT COALESCE(MAX(source_id), 0) FROM measurements WHERE device_id = ?',
            (device_id,),
        ).fetchone()[0]
    return int(value or 0)


def latest_contiguous_source_id(device_id: str = 'ecosensor01') -> int:
    """Devuelve el último source_id sincronizado sin huecos desde 1.

    No basta con MAX(source_id): si llegó por push la medición 970 pero faltan
    históricos 156..969, MAX=970 haría creer que no falta nada. Esta función
    encuentra el último ID continuo para reanudar /lecturas/since desde ahí.
    """
    ensure_db(device_id)
    expected = 1
    latest_contiguous = 0
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        rows = conn.execute(
            '''
            SELECT DISTINCT source_id
            FROM measurements
            WHERE device_id = ? AND source_id IS NOT NULL AND source_id > 0
            ORDER BY source_id ASC
            ''',
            (device_id,),
        )
        for row in rows:
            source_id = int(row[0] or 0)
            if source_id < expected:
                continue
            if source_id != expected:
                break
            latest_contiguous = source_id
            expected += 1
    return latest_contiguous


def missing_source_id_ranges(device_id: str = 'ecosensor01', remote_last_id: int = 0) -> list[tuple[int, int]]:
    """Rangos de source_id faltantes en SQLite, inclusivos y ascendentes."""
    remote_last_id = max(0, int(remote_last_id or 0))
    if remote_last_id <= 0:
        return []

    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        present = [
            int(row[0])
            for row in conn.execute(
                '''
                SELECT DISTINCT source_id
                FROM measurements
                WHERE device_id = ? AND source_id IS NOT NULL
                  AND source_id BETWEEN 1 AND ?
                ORDER BY source_id ASC
                ''',
                (device_id, remote_last_id),
            )
        ]

    ranges: list[tuple[int, int]] = []
    expected = 1
    for source_id in present:
        if source_id < expected:
            continue
        if source_id > expected:
            ranges.append((expected, source_id - 1))
        expected = source_id + 1
    if expected <= remote_last_id:
        ranges.append((expected, remote_last_id))
    return ranges


def _split_device_timestamp(timestamp: str | None) -> tuple[str, str]:
    return visible_date_time(timestamp)


def _graph_row(row: sqlite3.Row) -> dict[str, Any]:
    fecha, hora = _split_device_timestamp(row['device_timestamp'])
    return {
        '_row_id': row['source_id'] if row['source_id'] is not None else row['id'],
        'id': row['device_id'],
        'device_id': row['device_id'],
        'fecha': fecha,
        'hora': hora,
        'pm1p0': _round2_or_none(row['pm1p0']),
        'pm2p5': _round2_or_none(row['pm2p5']),
        'pm4p0': _round2_or_none(row['pm4p0']),
        'pm10p0': _round2_or_none(row['pm10p0']),
        'voc': _round2_or_none(row['voc']),
        'nox': _round2_or_none(row['nox']),
        'co2': _rounded_int_or_none(row['co2']),
        'temp': _round2_or_none(row['temp']),
        'hum': _rounded_int_or_none(row['hum']),
        'scd_temp': _round2_or_none(row['scd_temp']) if 'scd_temp' in row.keys() else None,
        'scd_hum': _round2_or_none(row['scd_hum']) if 'scd_hum' in row.keys() else None,
        'sen_temp': _round2_or_none(row['sen_temp']) if 'sen_temp' in row.keys() else None,
        'sen_hum': _round2_or_none(row['sen_hum']) if 'sen_hum' in row.keys() else None,
        'gps_valid': bool(row['gps_valid']) if 'gps_valid' in row.keys() and row['gps_valid'] is not None else None,
        'gps_lat': _float_or_none(row['gps_lat']) if 'gps_lat' in row.keys() else None,
        'gps_lon': _float_or_none(row['gps_lon']) if 'gps_lon' in row.keys() else None,
        'gps_satellites': _int_or_none(row['gps_satellites']) if 'gps_satellites' in row.keys() else None,
        'gps_hdop': _round2_or_none(row['gps_hdop']) if 'gps_hdop' in row.keys() else None,
    }


def graph_latest_row(device_id: str | None = None) -> dict[str, Any] | None:
    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum
            FROM measurements
            ORDER BY
                CASE WHEN source_id IS NOT NULL THEN 0 ELSE 1 END,
                source_id DESC,
                id DESC,
                received_at DESC
            LIMIT 1
            '''
        ).fetchone()
    return _graph_row(row) if row else None


def graph_rows_history(limit: int = 5000, device_id: str | None = None) -> list[dict[str, Any]]:
    ensure_db(device_id)
    limit = max(1, min(20000, int(limit)))
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum
            FROM (
                SELECT id, source_id, device_id, device_timestamp,
                       pm1p0, pm2p5, pm4p0, pm10p0,
                       voc, nox, co2, temp, hum
                FROM measurements
                ORDER BY COALESCE(source_id, id) DESC, id DESC
                LIMIT ?
            ) t
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            ''',
            (limit,),
        ).fetchall()
    return [_graph_row(row) for row in rows]


def graph_rows_all(device_id: str | None = None) -> list[dict[str, Any]]:
    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum, gps_valid, gps_lat, gps_lon, gps_satellites, gps_hdop
            FROM measurements
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            '''
        ).fetchall()
    return [_graph_row(row) for row in rows]


def graph_rows_count(device_id: str | None = None) -> int:
    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        value = conn.execute('SELECT COUNT(*) FROM measurements').fetchone()[0]
    return int(value or 0)


def graph_rows_page(offset: int = 0, limit: int = 1000, device_id: str | None = None) -> list[dict[str, Any]]:
    ensure_db(device_id)
    offset = max(0, int(offset))
    limit = max(1, min(5000, int(limit)))
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum, gps_valid, gps_lat, gps_lon, gps_satellites, gps_hdop
            FROM measurements
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            LIMIT ? OFFSET ?
            ''',
            (limit, offset),
        ).fetchall()
    return [_graph_row(row) for row in rows]


def graph_rows_since(row_id: int, limit: int = 500, device_id: str | None = None) -> list[dict[str, Any]]:
    ensure_db(device_id)
    row_id = max(0, int(row_id))
    limit = max(1, min(20000, int(limit)))
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum
            FROM measurements
            WHERE COALESCE(source_id, id) > ?
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            LIMIT ?
            ''',
            (row_id, limit),
        ).fetchall()
    return [_graph_row(row) for row in rows]


HISTORICAL_BACKFILLED_SOURCE = 'historical_backfilled'


INVALID_TIME_SOURCES = {
    'none', 'uptime', 'device_uptime', 'pending', 'pending_estimate',
    'invalid_history_time', 'invalid_timestamp', 'estimated',
}


def _explicitly_invalid_timestamp(row: sqlite3.Row) -> bool:
    source = str(row['time_source'] or '').strip().lower()
    timestamp = str(row['device_timestamp'] or '').strip()
    parsed = parse_timestamp(timestamp)
    if timestamp.upper().endswith('Z') and parsed is not None:
        return False
    return (
        row['time_valid'] == 0
        or not timestamp
        or parsed is None
        or source in INVALID_TIME_SOURCES
        or source.startswith('estimated')
    )


def _backup_before_time_repair(device_id: str | None) -> None:
    source = db_file_for_device(device_id)
    backup = source.with_suffix(source.suffix + '.pre_time_repair.bak')
    if source.exists() and not backup.exists():
        shutil.copy2(source, backup)


def repair_historical_invalid_timestamps(
    device_id: str | None = None,
    from_source_id: int | None = None,
    to_source_id: int | None = None,
) -> int:
    """Reconstruye solo filas marcadas explícitamente como inválidas.

    Una fecha ISO válida con Z u offset nunca se modifica. Se usan boot_id y
    uptime dentro del mismo arranque; si no están disponibles, se usa la
    separación por measurement_id/window_s entre anclas válidas.
    """
    ensure_db(device_id)
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, boot_id, uptime_s, device_timestamp,
                   time_valid, time_source, window_s
            FROM measurements
            WHERE source_id IS NOT NULL
            ORDER BY source_id ASC, id ASC
            '''
        ).fetchall()
        if not rows:
            return 0

        invalid_positions = [index for index, row in enumerate(rows) if _explicitly_invalid_timestamp(row)]
        if not invalid_positions:
            return 0

        source_from = _int_or_none(from_source_id)
        source_to = _int_or_none(to_source_id)
        if source_from is not None and source_to is not None and source_from > source_to:
            source_from, source_to = source_to, source_from

        updates: list[tuple[str, str | None, int]] = []
        for position in invalid_positions:
            row = rows[position]
            row_source_id = int(row['source_id'])
            if source_from is not None and row_source_id < source_from:
                continue
            if source_to is not None and row_source_id > source_to:
                continue

            candidate = None
            for direction in (1, -1):
                cursor = position + direction
                while 0 <= cursor < len(rows):
                    anchor = rows[cursor]
                    if not _explicitly_invalid_timestamp(anchor):
                        anchor_dt = parse_timestamp(anchor['device_timestamp'])
                        if anchor_dt is not None:
                            same_boot = row['boot_id'] is not None and row['boot_id'] == anchor['boot_id']
                            if same_boot and row['uptime_s'] is not None and anchor['uptime_s'] is not None:
                                delta = int(row['uptime_s']) - int(anchor['uptime_s'])
                            else:
                                step = max(1, int(row['window_s'] or 300))
                                delta = (row_source_id - int(anchor['source_id'])) * step
                            candidate = to_utc(anchor_dt) + timedelta(seconds=delta)
                            break
                    cursor += direction
                if candidate is not None:
                    break
            if candidate is not None:
                updates.append((iso_utc(candidate), row['device_timestamp'], int(row['id'])))

        if not updates:
            return 0
        _backup_before_time_repair(device_id)
        repaired = 0
        for timestamp, original, row_id in updates:
            cursor = conn.execute(
                '''
                UPDATE measurements
                SET original_device_timestamp = COALESCE(original_device_timestamp, ?),
                    device_timestamp = ?, time_valid = 1, time_source = ?
                WHERE id = ?
                ''',
                (original, timestamp, HISTORICAL_BACKFILLED_SOURCE, row_id),
            )
            repaired += int(cursor.rowcount or 0)
        conn.commit()
        return repaired


def repair_future_estimated_timestamps(device_id: str | None = None) -> int:
    """Compatibilidad: ya no sustituye timestamps válidos por received_at."""
    ensure_db(device_id)
    return 0


def _csv_date_display(value: str | None) -> str:
    parsed = _parse_timestamp_local(str(value or ''))
    if parsed is None:
        text = str(value or '').strip()
        return text
    return parsed.strftime('%d-%m-%Y')


def measurements_csv_text(device_id: str | None = None) -> str:
    ensure_db(device_id)
    output = io.StringIO()
    fieldnames = [
        'id', 'device_id', 'Fecha de medicion', 'Hora de medicion',
        'PM1.0', 'PM2.5', 'PM4.0', 'PM10.0',
        'VOC', 'NOx', 'CO2', 'Temperatura', 'Humedad',
        'Latitud', 'Longitud',
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum,
                   gps_lat, gps_lon
            FROM measurements
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            '''
        )
        for row in rows:
            date_part, time_part = _split_device_timestamp(row['device_timestamp'])
            writer.writerow({
                'id': row['source_id'] if row['source_id'] is not None else row['id'],
                'device_id': row['device_id'],
                'Fecha de medicion': _csv_date_display(row['device_timestamp']),
                'Hora de medicion': time_part,
                'PM1.0': _csv_decimal(row['pm1p0']),
                'PM2.5': _csv_decimal(row['pm2p5']),
                'PM4.0': _csv_decimal(row['pm4p0']),
                'PM10.0': _csv_decimal(row['pm10p0']),
                'VOC': _csv_decimal(row['voc']),
                'NOx': _csv_decimal(row['nox']),
                'CO2': _csv_int(row['co2']),
                'Temperatura': _csv_decimal(row['temp']),
                'Humedad': _csv_int(row['hum']),
                'Latitud': '' if row['gps_lat'] is None else f"{float(row['gps_lat']):.6f}",
                'Longitud': '' if row['gps_lon'] is None else f"{float(row['gps_lon']):.6f}",
            })

    return output.getvalue()


def _source_id_blocks(source_ids: list[int]) -> list[dict[str, int]]:
    """Agrupa source_id consecutivos para mensajes claros de validación."""
    if not source_ids:
        return []
    blocks: list[dict[str, int]] = []
    start = previous = source_ids[0]
    for source_id in source_ids[1:]:
        if source_id == previous + 1:
            previous = source_id
            continue
        blocks.append({'from': start, 'to': previous, 'count': previous - start + 1})
        start = previous = source_id
    blocks.append({'from': start, 'to': previous, 'count': previous - start + 1})
    return blocks


def validate_measurements_for_csv(device_id: str | None = None) -> dict[str, Any]:
    """Valida que el CSV general no vaya a salir con fecha/hora inválida.

    La descarga general es un producto para usuario final; no debe generarse si
    hay historial con timestamp vacío, no parseable, `time_valid=0` o marcado
    como `pending_estimate`. En esos casos se devuelve un resumen para mostrar
    un bloqueo explícito en la UI/API.
    """
    safe_id = _safe_device_id(device_id)
    ensure_db(safe_id)

    invalid_ids: list[int] = []
    invalid_samples: list[dict[str, Any]] = []
    previous: tuple[int, datetime] | None = None
    backwards: list[dict[str, Any]] = []

    with sqlite3.connect(db_file_for_device(safe_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_timestamp, time_valid, time_source
            FROM measurements
            WHERE device_id = ?
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            ''',
            (safe_id,),
        ).fetchall()

    for row in rows:
        row_id = int(row['source_id'] if row['source_id'] is not None else row['id'])
        timestamp = str(row['device_timestamp'] or '').strip()
        parsed = _parse_timestamp_local(timestamp)
        source = str(row['time_source'] or '').strip().lower()
        invalid = (
            not timestamp
            or parsed is None
            or row['time_valid'] == 0
            or source == 'pending_estimate'
        )
        if invalid:
            invalid_ids.append(row_id)
            if len(invalid_samples) < 10:
                invalid_samples.append({
                    'source_id': row_id,
                    'timestamp': timestamp or None,
                    'time_valid': row['time_valid'],
                    'time_source': row['time_source'],
                })
            continue
        if parsed is not None and row['source_id'] is not None:
            current = (int(row['source_id']), parsed)
            if previous is not None and current[0] > previous[0] and current[1] < previous[1]:
                backwards.append({
                    'source_id': current[0],
                    'timestamp': current[1].isoformat(timespec='seconds'),
                    'previous_source_id': previous[0],
                    'previous_timestamp': previous[1].isoformat(timespec='seconds'),
                })
            previous = current

    invalid_blocks = _source_id_blocks(invalid_ids)
    ok = not invalid_ids and not backwards
    message = 'Datos listos para descargar CSV.'
    if invalid_ids:
        first_blocks = ', '.join(
            f"{item['from']}–{item['to']}" if item['from'] != item['to'] else str(item['from'])
            for item in invalid_blocks[:5]
        )
        message = (
            f'No se puede descargar el CSV de {safe_id}. '
            f'Hay {len(invalid_ids)} mediciones sin fecha/hora válida. '
            f'Bloques afectados: {first_blocks}.'
        )
    elif backwards:
        message = (
            f'No se puede descargar el CSV de {safe_id}. '
            f'Hay {len(backwards)} saltos cronológicos hacia atrás por source_id.'
        )

    return {
        'ok': ok,
        'device_id': safe_id,
        'total_rows': len(rows),
        'invalid_count': len(invalid_ids),
        'invalid_blocks': invalid_blocks,
        'invalid_samples': invalid_samples,
        'backwards_count': len(backwards),
        'backwards_samples': backwards[:10],
        'message': message,
    }


def _parse_timestamp_local(value: Any) -> datetime | None:
    parsed = parse_timestamp(value)
    return to_server_local(parsed).replace(tzinfo=None) if parsed is not None else None


def _sanitize_device_timestamp(device_timestamp: Any, received_at: str, time_source: str | None, time_valid: int | None, source_id: int | None = None) -> tuple[str | None, str | None, int | None]:
    if not device_timestamp:
        return None, time_source, time_valid
    timestamp_text = str(device_timestamp)
    if parse_timestamp(timestamp_text) is not None:
        return timestamp_text, time_source, time_valid
    # Se conserva el valor original para diagnóstico; una consulta o recepción
    # nunca inventa una hora válida ni la sustituye por received_at.
    return timestamp_text, time_source or 'invalid_timestamp', 0


INSERT_MEASUREMENT_SQL = '''
INSERT OR IGNORE INTO measurements (
    device_id, host, device_timestamp, received_at, source_id,
    boot_id, uptime_s, time_valid, time_source,
    pm1p0, pm2p5, pm4p0, pm10p0,
    voc, nox, co2, temp, hum, scd_temp, scd_hum, sen_temp, sen_hum,
    gps_valid, gps_lat, gps_lon, gps_satellites, gps_hdop, gps_age_ms, window_s
) VALUES (
    :device_id, :host, :device_timestamp, :received_at, :source_id,
    :boot_id, :uptime_s, :time_valid, :time_source,
    :pm1p0, :pm2p5, :pm4p0, :pm10p0,
    :voc, :nox, :co2, :temp, :hum, :scd_temp, :scd_hum, :sen_temp, :sen_hum,
    :gps_valid, :gps_lat, :gps_lon, :gps_satellites, :gps_hdop, :gps_age_ms, :window_s
)
'''

UPDATE_MEASUREMENT_SQL = '''
UPDATE measurements
SET host = :host,
    device_timestamp = CASE WHEN :time_valid = 1 THEN :device_timestamp ELSE device_timestamp END,
    received_at = :received_at,
    boot_id = COALESCE(:boot_id, boot_id),
    uptime_s = COALESCE(:uptime_s, uptime_s),
    time_valid = CASE WHEN :time_valid = 1 THEN 1 ELSE COALESCE(time_valid, :time_valid) END,
    time_source = CASE WHEN :time_valid = 1 THEN :time_source ELSE COALESCE(time_source, :time_source) END,
    pm1p0 = COALESCE(:pm1p0, pm1p0),
    pm2p5 = COALESCE(:pm2p5, pm2p5),
    pm4p0 = COALESCE(:pm4p0, pm4p0),
    pm10p0 = COALESCE(:pm10p0, pm10p0),
    voc = COALESCE(:voc, voc),
    nox = COALESCE(:nox, nox),
    co2 = COALESCE(:co2, co2),
    temp = COALESCE(:temp, temp),
    hum = COALESCE(:hum, hum),
    scd_temp = COALESCE(:scd_temp, scd_temp),
    scd_hum = COALESCE(:scd_hum, scd_hum),
    sen_temp = COALESCE(:sen_temp, sen_temp),
    sen_hum = COALESCE(:sen_hum, sen_hum),
    gps_valid = COALESCE(:gps_valid, gps_valid),
    gps_lat = COALESCE(:gps_lat, gps_lat),
    gps_lon = COALESCE(:gps_lon, gps_lon),
    gps_satellites = COALESCE(:gps_satellites, gps_satellites),
    gps_hdop = COALESCE(:gps_hdop, gps_hdop),
    gps_age_ms = COALESCE(:gps_age_ms, gps_age_ms),
    window_s = COALESCE(:window_s, window_s)
WHERE device_id = :device_id AND source_id = :source_id
  AND (
    COALESCE(time_source, '') NOT IN ('esp_push', 'esp_live')
    OR :prefer_live_source = 1
  )
'''


def _measurement_values(host: str, row: dict[str, Any], received_at: str | None = None) -> dict[str, Any]:
    received_at = received_at or utc_now_iso()
    device_id = str(row.get('id') or row.get('device_id') or '').strip() or 'ecosensor01'
    device_timestamp = row.get('timestamp') or None
    source_id = _source_id_from_row(row)
    time_valid_bool = _bool_or_none(row.get('time_valid'))
    time_valid = None if time_valid_bool is None else int(time_valid_bool)
    time_source = row.get('time_source') or ('esp' if time_valid else 'uptime' if time_valid == 0 else None)
    device_timestamp, time_source, time_valid = _sanitize_device_timestamp(
        device_timestamp,
        received_at,
        time_source,
        time_valid,
        source_id,
    )
    gps_valid_value = _bool_or_none(row.get('gps_valid'))
    gps_valid = None if gps_valid_value is None else int(bool(gps_valid_value))
    gps_lat = _float_or_none(row.get('gps_lat'))
    gps_lon = _float_or_none(row.get('gps_lon'))
    if not gps_valid:
        gps_lat = None
        gps_lon = None

    return {
        'device_id': device_id,
        'host': host,
        'device_timestamp': device_timestamp,
        'received_at': received_at,
        'source_id': source_id,
        'boot_id': _int_or_none(row.get('boot_id')),
        'uptime_s': _int_or_none(row.get('uptime_s')),
        'time_valid': time_valid,
        'time_source': time_source,
        'pm1p0': _round2_or_none(row.get('pm1p0')),
        'pm2p5': _round2_or_none(row.get('pm2p5')),
        'pm4p0': _round2_or_none(row.get('pm4p0')),
        'pm10p0': _round2_or_none(row.get('pm10p0')),
        'voc': _round2_or_none(row.get('voc')),
        'nox': _round2_or_none(row.get('nox')),
        'co2': _rounded_int_or_none(row.get('co2')),
        'temp': _round2_or_none(row.get('temp')),
        'hum': _rounded_int_or_none(row.get('hum')),
        'scd_temp': _round2_or_none(row.get('scd_temp')),
        'scd_hum': _round2_or_none(row.get('scd_hum')),
        'sen_temp': _round2_or_none(row.get('sen_temp')),
        'sen_hum': _round2_or_none(row.get('sen_hum')),
        'gps_valid': gps_valid,
        'gps_lat': gps_lat,
        'gps_lon': gps_lon,
        'gps_satellites': _int_or_none(row.get('gps_satellites')),
        'gps_hdop': _round2_or_none(row.get('gps_hdop')),
        'gps_age_ms': _int_or_none(row.get('gps_age_ms')),
        'window_s': _int_or_none(row.get('window_s')),
    }


def save_measurement(host: str, row: dict[str, Any]) -> bool:
    """Guarda una medición válida. Devuelve True si insertó una fila nueva."""
    device_id = str(row.get('id') or row.get('device_id') or '').strip() or 'ecosensor01'
    ensure_db(device_id)
    values = _measurement_values(host, row)
    source_id = values.get('source_id')
    device_timestamp = values.get('device_timestamp')
    time_source = values.get('time_source')

    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        cursor = conn.execute(INSERT_MEASUREMENT_SQL, values)
        inserted = cursor.rowcount > 0
        if not inserted and source_id is not None and device_timestamp:
            prefer_live_source = time_source in {'esp_push', 'esp_live', 'gps', 'ntp', 'server'}
            conn.execute(UPDATE_MEASUREMENT_SQL, {**values, 'prefer_live_source': 1 if prefer_live_source else 0})
        conn.commit()
        return inserted


def save_measurements_bulk(host: str, rows: list[dict[str, Any]], device_id: str | None = None) -> int:
    """Guarda muchas mediciones en una sola transacción. Devuelve filas nuevas insertadas."""
    if not rows:
        return 0
    target_device_id = str(device_id or rows[0].get('id') or rows[0].get('device_id') or '').strip() or 'ecosensor01'
    ensure_db(target_device_id)
    received_at = utc_now_iso()
    values_list = [_measurement_values(host, row, received_at) for row in rows]
    inserted = 0
    with sqlite3.connect(db_file_for_device(target_device_id)) as conn:
        for values in values_list:
            cursor = conn.execute(INSERT_MEASUREMENT_SQL, values)
            if cursor.rowcount > 0:
                inserted += 1
                continue
            source_id = values.get('source_id')
            device_timestamp = values.get('device_timestamp')
            if source_id is not None and device_timestamp:
                prefer_live_source = values.get('time_source') in {'esp_push', 'esp_live', 'gps', 'ntp', 'server'}
                conn.execute(UPDATE_MEASUREMENT_SQL, {**values, 'prefer_live_source': 1 if prefer_live_source else 0})
        conn.commit()
    return inserted
