from __future__ import annotations

from typing import Any

from services.device_registry import probe_host
from services.esp_client import build_endpoints, delete_json


EXPECTED_RESTART_DISCONNECTS = (
    'remote end closed connection',
    'connection reset by peer',
    'connection aborted',
)


def _is_expected_restart_disconnect(result: dict[str, Any]) -> bool:
    if int(result.get('status') or 0) != 0:
        return False
    detail = str(result.get('data') or '').strip().lower()
    return any(fragment in detail for fragment in EXPECTED_RESTART_DISCONNECTS)


async def clear_device_wifi(device_id: str, host: str) -> dict[str, Any]:
    """Valida el EcoSensor y solicita el borrado de WiFi.

    El firmware puede reiniciar antes de completar la respuesta HTTP. Esa
    desconexión solo se acepta como resultado probable después de comprobar
    inmediatamente que el host corresponde al device_id solicitado.
    """
    expected_device_id = str(device_id or '').strip().lower()
    detected = await probe_host(host, timeout=1.5)
    if not detected:
        return {
            'ok': False,
            'error': 'device_unreachable_before_wifi_clear',
            'message': 'el EcoSensor no respondió a la validación previa; no se envió la orden',
        }

    detected_device_id = str(detected.get('device_id') or '').strip().lower()
    if detected_device_id != expected_device_id:
        return {
            'ok': False,
            'error': 'device_identity_mismatch',
            'message': f'identidad inesperada: se esperaba {expected_device_id} y respondió {detected_device_id or "desconocida"}',
        }

    result = await delete_json(build_endpoints(host)['wifi_clear'], timeout=8.0)
    if result.get('ok'):
        return {'ok': True, 'confirmed': True, 'response': result}
    if _is_expected_restart_disconnect(result):
        return {'ok': True, 'confirmed': False, 'response': result}
    return {
        'ok': False,
        'error': 'wifi_clear_failed',
        'message': str(result.get('data') or 'respuesta no válida del EcoSensor'),
        'response': result,
    }
