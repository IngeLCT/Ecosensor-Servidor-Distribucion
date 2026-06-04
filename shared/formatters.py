from typing import Any

from config import DEVICE_ID


def device_display_name(device_id: str = DEVICE_ID) -> str:
    suffix = ''.join(ch for ch in device_id if ch.isdigit())
    return f'EcoSensor{suffix or "01"}'


def _float_or_none(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round2_or_none(value: Any) -> float | None:
    number = _float_or_none(value)
    return None if number is None else round(number, 2)


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return None if number is None else int(round(number))


def row_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        'id': payload.get('device_id', DEVICE_ID),
        'measurement_id': payload.get('measurement_id') or payload.get('id'),
        'boot_id': payload.get('boot_id'),
        'uptime_s': payload.get('uptime_s'),
        'time_valid': payload.get('time_valid'),
        'time_source': payload.get('time_source'),
        'timestamp': payload.get('timestamp'),
        'pm1p0': _round2_or_none(payload.get('pm1p0')),
        'pm2p5': _round2_or_none(payload.get('pm2p5')),
        'pm4p0': _round2_or_none(payload.get('pm4p0')),
        'pm10p0': _round2_or_none(payload.get('pm10p0')),
        'voc': _round2_or_none(payload.get('voc')),
        'nox': _round2_or_none(payload.get('nox')),
        'co2': _int_or_none(payload.get('co2')),
        'temp': _round2_or_none(payload.get('temp')),
        'hum': _int_or_none(payload.get('hum')),
        'scd_temp': _round2_or_none(payload.get('scd_temp')),
        'scd_hum': _round2_or_none(payload.get('scd_hum')),
        'sen_temp': _round2_or_none(payload.get('sen_temp')),
        'sen_hum': _round2_or_none(payload.get('sen_hum')),
        'gps_valid': payload.get('gps_valid'),
        'gps_lat': _float_or_none(payload.get('gps_lat')),
        'gps_lon': _float_or_none(payload.get('gps_lon')),
        'gps_satellites': _int_or_none(payload.get('gps_satellites')),
        'gps_hdop': _round2_or_none(payload.get('gps_hdop')),
        'gps_age_ms': _int_or_none(payload.get('gps_age_ms')),
        'window_s': payload.get('window_s'),
    }


def format_value(value: Any, decimals: int = 2) -> str:
    if value is None:
        return '0'
    if decimals == 0:
        try:
            return str(int(round(float(value))))
        except (TypeError, ValueError):
            return str(value)
    try:
        return f'{float(value):.{decimals}f}'
    except (TypeError, ValueError):
        return str(value)
