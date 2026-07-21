from __future__ import annotations

from typing import Any

_resetting: set[str] = set()
_awaiting_first_id: set[str] = set()
_quarantined_pushes: dict[str, list[dict[str, Any]]] = {}


def begin_history_reset(device_id: str) -> None:
    _resetting.add(device_id)
    _awaiting_first_id.discard(device_id)
    _quarantined_pushes.pop(device_id, None)


def finish_history_reset(device_id: str, *, confirmed: bool) -> None:
    _resetting.discard(device_id)
    if confirmed:
        _awaiting_first_id.add(device_id)
    else:
        _awaiting_first_id.discard(device_id)


def history_reset_in_progress(device_id: str) -> bool:
    return device_id in _resetting


def quarantine_push(device_id: str, payload: dict[str, Any]) -> None:
    rows = _quarantined_pushes.setdefault(device_id, [])
    rows.append(dict(payload))
    del rows[:-10]


def accept_push_id(device_id: str, measurement_id: Any) -> tuple[bool, str]:
    if history_reset_in_progress(device_id):
        return False, 'history_reset_in_progress'
    if device_id not in _awaiting_first_id:
        return True, ''
    try:
        parsed = int(measurement_id)
    except (TypeError, ValueError):
        parsed = 0
    if parsed != 1:
        return False, 'awaiting_measurement_id_1'
    _awaiting_first_id.discard(device_id)
    return True, ''


def reset_state_snapshot(device_id: str) -> dict[str, Any]:
    return {
        'history_reset_in_progress': device_id in _resetting,
        'awaiting_first_measurement': device_id in _awaiting_first_id,
        'quarantined_pushes': len(_quarantined_pushes.get(device_id, [])),
    }
