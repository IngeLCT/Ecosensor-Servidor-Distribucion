import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from config import DATA_DIR, MEASUREMENTS_DB_FILE


TIMESTAMP_DRIFT_TOLERANCE_SECONDS = 15 * 60


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
    repair_future_estimated_timestamps(device_id)
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
                COALESCE(
                    datetime(replace(replace(substr(device_timestamp, 1, 19), 'T', ' '), 'Z', '')),
                    datetime(replace(replace(substr(received_at, 1, 19), 'T', ' '), 'Z', ''))
                ) DESC
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
    value = (timestamp or '').strip()
    if not value:
        return '', ''
    if 'T' in value:
        date_part, time_part = value.split('T', 1)
        return date_part, time_part.rstrip('Z').split('+', 1)[0].split('-', 1)[0]
    if ' ' in value:
        date_part, time_part = value.split(' ', 1)
        return date_part, time_part.rstrip('Z')
    return value, ''


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
    repair_future_estimated_timestamps(device_id)
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
                COALESCE(
                    datetime(replace(replace(substr(device_timestamp, 1, 19), 'T', ' '), 'Z', '')),
                    datetime(replace(replace(substr(received_at, 1, 19), 'T', ' '), 'Z', ''))
                ) DESC
            LIMIT 1
            '''
        ).fetchone()
    return _graph_row(row) if row else None


def graph_rows_history(limit: int = 5000, device_id: str | None = None) -> list[dict[str, Any]]:
    ensure_db(device_id)
    repair_future_estimated_timestamps(device_id)
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
    repair_future_estimated_timestamps(device_id)
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


def graph_rows_since(row_id: int, limit: int = 500, device_id: str | None = None) -> list[dict[str, Any]]:
    ensure_db(device_id)
    repair_future_estimated_timestamps(device_id)
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
LEGACY_HISTORICAL_BACKFILLED_SOURCE = 'backfilled_from_next_valid'


def _is_invalid_historical_time(row: sqlite3.Row) -> bool:
    if row['source_id'] is None:
        return False
    source = str(row['time_source'] or '').lower()
    if source in {HISTORICAL_BACKFILLED_SOURCE, LEGACY_HISTORICAL_BACKFILLED_SOURCE}:
        return False
    if row['time_valid'] == 0:
        return True
    if source.startswith('estimated') or 'drift_corrected' in source:
        return True
    return not str(row['device_timestamp'] or '').strip()


def repair_historical_invalid_timestamps(
    device_id: str | None = None,
    from_source_id: int | None = None,
    to_source_id: int | None = None,
) -> int:
    """Reconstruye horas históricas inválidas usando la siguiente medición válida.

    No usa la hora de recepción del servidor para historial. Detecta dos casos:
    1) filas marcadas como inválidas/estimadas;
    2) filas con fecha aparentemente válida pero imposible por el orden de IDs,
       por ejemplo un ID con fecha posterior a otra medición futura.

    Para cada corrida sospechosa, toma la siguiente medición no sospechosa como
    ancla, resta window_s (5 min por defecto) para el ID anterior y continúa
    hacia atrás sin solaparse con la medición válida previa.

    Si se indica un rango de source_id, solo se revisan esas mediciones nuevas
    más la medición válida anterior y posterior más cercanas. Esto evita
    reanalizar todo el histórico en cada sincronización.
    """
    ensure_db(device_id)
    repaired = 0
    source_from = _int_or_none(from_source_id)
    source_to = _int_or_none(to_source_id)
    if source_from is not None and source_to is not None and source_from > source_to:
        source_from, source_to = source_to, source_from

    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        if source_from is not None and source_to is not None:
            rows = conn.execute(
                '''
                WITH scoped AS (
                    SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                    FROM measurements
                    WHERE source_id BETWEEN ? AND ?
                    UNION ALL
                    SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                    FROM measurements
                    WHERE source_id = (
                        SELECT MAX(source_id) FROM measurements WHERE source_id < ?
                    )
                    UNION ALL
                    SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                    FROM measurements
                    WHERE source_id = (
                        SELECT MIN(source_id) FROM measurements WHERE source_id > ?
                    )
                )
                SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                FROM scoped
                WHERE source_id IS NOT NULL
                GROUP BY id
                ORDER BY source_id ASC, id ASC
                ''',
                (source_from, source_to, source_from, source_to),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                FROM measurements
                WHERE source_id IS NOT NULL
                ORDER BY source_id ASC, id ASC
                '''
            ).fetchall()
        if not rows:
            return 0

        parsed_times = [_parse_timestamp_local(row['device_timestamp']) for row in rows]

        # Referencias cronológicas por source_id:
        # - future_min detecta fechas adelantadas respecto a una medición futura.
        # - previous_max detecta cambios de día fallidos, donde el reloj vuelve a
        #   00:xx pero conserva el día anterior y queda detrás de una medición previa.
        future_min: list[datetime | None] = [None] * len(rows)
        current_min: datetime | None = None
        for pos in range(len(rows) - 1, -1, -1):
            future_min[pos] = current_min
            parsed = parsed_times[pos]
            if parsed is not None and (current_min is None or parsed < current_min):
                current_min = parsed

        base_suspicious: list[bool] = []
        for pos, row in enumerate(rows):
            parsed = parsed_times[pos]
            invalid = _is_invalid_historical_time(row) or parsed is None
            future_order_impossible = (
                parsed is not None
                and future_min[pos] is not None
                and parsed >= future_min[pos]
            )
            base_suspicious.append(invalid or future_order_impossible)

        previous_valid_max: list[datetime | None] = [None] * len(rows)
        current_valid_max: datetime | None = None
        for pos, parsed in enumerate(parsed_times):
            previous_valid_max[pos] = current_valid_max
            if not base_suspicious[pos] and parsed is not None and (current_valid_max is None or parsed > current_valid_max):
                current_valid_max = parsed

        suspicious: list[bool] = []
        for pos, parsed in enumerate(parsed_times):
            past_order_impossible = (
                not base_suspicious[pos]
                and parsed is not None
                and previous_valid_max[pos] is not None
                and parsed <= previous_valid_max[pos]
            )
            suspicious.append(base_suspicious[pos] or past_order_impossible)

        index = 0
        previous_valid_dt: datetime | None = None
        while index < len(rows):
            if not suspicious[index]:
                previous_valid_dt = parsed_times[index]
                index += 1
                continue

            run_start = index
            while index < len(rows) and suspicious[index]:
                index += 1
            run = rows[run_start:index]
            if not run or index >= len(rows):
                continue

            next_valid_dt = parsed_times[index]
            if next_valid_dt is None:
                continue

            cursor = next_valid_dt
            updates: list[tuple[str, str, int]] = []
            for invalid_row in reversed(run):
                try:
                    step = max(1, int(invalid_row['window_s'] or 300))
                except (TypeError, ValueError):
                    step = 300
                candidate = cursor - timedelta(seconds=step)
                if previous_valid_dt is not None and candidate <= previous_valid_dt:
                    break
                updates.append((candidate.isoformat(timespec='seconds'), HISTORICAL_BACKFILLED_SOURCE, invalid_row['id']))
                cursor = candidate

            for timestamp, source, row_id in updates:
                cursor = conn.execute(
                    '''
                    UPDATE measurements
                    SET device_timestamp = ?, time_valid = 1, time_source = ?
                    WHERE id = ?
                      AND (
                        COALESCE(device_timestamp, '') != ?
                        OR COALESCE(time_valid, -1) != 1
                        OR COALESCE(time_source, '') != ?
                      )
                    ''',
                    (timestamp, source, row_id, timestamp, source),
                )
                repaired += int(cursor.rowcount or 0)

        conn.commit()

        # Segunda pasada defensiva: garantiza monotonía por source_id.
        # Si una medición anterior quedó con hora igual/posterior a la siguiente,
        # se reconstruye hacia atrás usando window_s. Esto corrige bloques largos
        # adelantados que no siempre quedan cubiertos por la detección por anclas.
        if source_from is not None and source_to is not None:
            rows = conn.execute(
                '''
                WITH scoped AS (
                    SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                    FROM measurements
                    WHERE source_id BETWEEN ? AND ?
                    UNION ALL
                    SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                    FROM measurements
                    WHERE source_id = (
                        SELECT MAX(source_id) FROM measurements WHERE source_id < ?
                    )
                    UNION ALL
                    SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                    FROM measurements
                    WHERE source_id = (
                        SELECT MIN(source_id) FROM measurements WHERE source_id > ?
                    )
                )
                SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                FROM scoped
                WHERE source_id IS NOT NULL
                GROUP BY id
                ORDER BY source_id ASC, id ASC
                ''',
                (source_from, source_to, source_from, source_to),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT id, source_id, device_timestamp, time_valid, time_source, window_s
                FROM measurements
                WHERE source_id IS NOT NULL
                ORDER BY source_id ASC, id ASC
                '''
            ).fetchall()

        next_valid_dt: datetime | None = None
        monotonic_updates: list[tuple[str, str, int]] = []
        for row in reversed(rows):
            parsed = _parse_timestamp_local(row['device_timestamp'])
            if parsed is None:
                continue
            if next_valid_dt is not None and parsed >= next_valid_dt:
                try:
                    step = max(1, int(row['window_s'] or 300))
                except (TypeError, ValueError):
                    step = 300
                parsed = next_valid_dt - timedelta(seconds=step)
                monotonic_updates.append((parsed.isoformat(timespec='seconds'), HISTORICAL_BACKFILLED_SOURCE, row['id']))
            next_valid_dt = parsed

        for timestamp, source, row_id in monotonic_updates:
            cursor = conn.execute(
                '''
                UPDATE measurements
                SET device_timestamp = ?, time_valid = 1, time_source = ?
                WHERE id = ?
                  AND (
                    COALESCE(device_timestamp, '') != ?
                    OR COALESCE(time_valid, -1) != 1
                    OR COALESCE(time_source, '') != ?
                  )
                ''',
                (timestamp, source, row_id, timestamp, source),
            )
            repaired += int(cursor.rowcount or 0)
        conn.commit()
    return repaired


def repair_future_estimated_timestamps(device_id: str | None = None) -> int:
    """Corrige timestamps de dispositivo fuera de tolerancia contra received_at.

    La hora del EcoSensor puede quedar marcada como válida aunque esté adelantada
    o atrasada. Durante sincronización/consulta, si la diferencia entre
    device_timestamp y la hora de recepción del servidor supera ±15 minutos, se
    reemplaza por received_at local y se marca como corregida.
    """
    ensure_db(device_id)
    repaired = 0
    with sqlite3.connect(db_file_for_device(device_id)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_timestamp, received_at, time_source
            FROM measurements
            WHERE device_timestamp IS NOT NULL AND device_timestamp != ''
              AND received_at IS NOT NULL AND received_at != ''
              AND source_id IS NULL
              AND COALESCE(time_source, '') NOT LIKE '%drift_corrected'
            '''
        ).fetchall()
        for row in rows:
            device_ts = _parse_timestamp_local(row['device_timestamp'])
            if device_ts is None:
                continue
            try:
                received_local = _received_at_local(str(row['received_at']))
            except ValueError:
                continue
            drift_s = abs((device_ts - received_local).total_seconds())
            if drift_s <= TIMESTAMP_DRIFT_TOLERANCE_SECONDS:
                continue
            original_source = str(row['time_source'] or 'esp')
            corrected_source = f'{original_source}_drift_corrected'
            conn.execute(
                '''
                UPDATE measurements
                SET device_timestamp = ?, time_valid = 0, time_source = ?
                WHERE id = ?
                ''',
                (received_local.isoformat(timespec='seconds'), corrected_source, row['id']),
            )
            repaired += 1
        conn.commit()
    return repaired


def measurements_csv_text(device_id: str | None = None) -> str:
    ensure_db(device_id)
    repair_future_estimated_timestamps(device_id)
    repair_historical_invalid_timestamps(device_id)
    output = io.StringIO()
    fieldnames = [
        'id', 'device_id', 'Fecha de medicion', 'Hora de medicion',
        'PM1.0', 'PM2.5', 'PM4.0', 'PM10.0',
        'VOC', 'NOx', 'CO2', 'Temperatura', 'Humedad',
        'GPS valido', 'Latitud', 'Longitud', 'Satellites GPS', 'HDOP GPS',
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
                   gps_valid, gps_lat, gps_lon, gps_satellites, gps_hdop
            FROM measurements
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            '''
        )
        for row in rows:
            date_part, time_part = _split_device_timestamp(row['device_timestamp'])
            writer.writerow({
                'id': row['source_id'] if row['source_id'] is not None else row['id'],
                'device_id': row['device_id'],
                'Fecha de medicion': date_part,
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
                'GPS valido': '1' if row['gps_valid'] else '0' if row['gps_valid'] is not None else '',
                'Latitud': '' if row['gps_lat'] is None else f"{float(row['gps_lat']):.6f}",
                'Longitud': '' if row['gps_lon'] is None else f"{float(row['gps_lon']):.6f}",
                'Satellites GPS': _csv_int(row['gps_satellites']),
                'HDOP GPS': _csv_decimal(row['gps_hdop']),
            })

    return output.getvalue()



def _parse_timestamp_local(value: Any) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1]
    if 'T' in text:
        text = text.replace('T', ' ', 1)
    if '+' in text:
        text = text.split('+', 1)[0]
    if len(text) > 19:
        text = text[:19]
    for fmt in ('%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _received_at_local(received_at: str) -> datetime:
    parsed = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
    return parsed.astimezone().replace(tzinfo=None)


def _sanitize_device_timestamp(device_timestamp: Any, received_at: str, time_source: str | None, time_valid: int | None, source_id: int | None = None) -> tuple[str | None, str | None, int | None]:
    if not device_timestamp:
        return None, time_source, time_valid

    # Las lecturas historicas del EcoSensor llegan en lote y pueden guardarse
    # varios minutos/horas despues de su medicion real. Si se comparan contra
    # received_at, se destruye su hora original y muchas filas quedan con el
    # mismo segundo de importacion. Solo corregimos drift en lecturas en vivo
    # sin source_id/measurement_id.
    if source_id is not None:
        return str(device_timestamp), time_source, time_valid

    timestamp_text = str(device_timestamp)
    parsed_device = _parse_timestamp_local(timestamp_text)
    if parsed_device is None:
        return timestamp_text, time_source, time_valid

    received_local = _received_at_local(received_at)
    drift_s = abs((parsed_device - received_local).total_seconds())
    if drift_s <= TIMESTAMP_DRIFT_TOLERANCE_SECONDS:
        return timestamp_text, time_source, time_valid

    corrected = received_local.isoformat(timespec='seconds')
    corrected_source = f'{time_source or "esp"}_drift_corrected'
    return corrected, corrected_source, 0


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
    device_timestamp = :device_timestamp,
    received_at = :received_at,
    boot_id = COALESCE(:boot_id, boot_id),
    uptime_s = COALESCE(:uptime_s, uptime_s),
    time_valid = COALESCE(:time_valid, time_valid),
    time_source = COALESCE(:time_source, time_source),
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
    received_at = received_at or datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    device_id = str(row.get('id') or row.get('device_id') or '').strip() or 'ecosensor01'
    device_timestamp = row.get('timestamp') or None
    source_id = _source_id_from_row(row)
    time_valid_bool = _bool_or_none(row.get('time_valid'))
    time_valid = None if time_valid_bool is None else int(time_valid_bool)
    time_source = row.get('time_source') or ('esp' if time_valid else 'estimated' if time_valid == 0 else None)
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
            prefer_live_source = time_source in {'esp_push', 'esp_live'}
            conn.execute(UPDATE_MEASUREMENT_SQL, {**values, 'prefer_live_source': 1 if prefer_live_source else 0})
        conn.commit()
        return inserted


def save_measurements_bulk(host: str, rows: list[dict[str, Any]], device_id: str | None = None) -> int:
    """Guarda muchas mediciones en una sola transacción. Devuelve filas nuevas insertadas."""
    if not rows:
        return 0
    target_device_id = str(device_id or rows[0].get('id') or rows[0].get('device_id') or '').strip() or 'ecosensor01'
    ensure_db(target_device_id)
    received_at = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
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
                prefer_live_source = values.get('time_source') in {'esp_push', 'esp_live'}
                conn.execute(UPDATE_MEASUREMENT_SQL, {**values, 'prefer_live_source': 1 if prefer_live_source else 0})
        conn.commit()
    return inserted
