from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from typing import Any
from urllib.parse import quote

from config import FIRMWARE_DIR, get_selected_ui_port
from services.device_registry import ensure_device_active
from services.esp_client import fetch_ota_status, start_ota_update


class OtaError(ValueError):
    pass


def _clean_device_id(value: str) -> str:
    clean = str(value or '').strip().lower()
    if clean not in {'ecosensor01', 'ecosensor02', 'ecosensor03'}:
        raise OtaError('device_id OTA no permitido')
    return clean


def _device_dir(device_id: str) -> Path:
    return FIRMWARE_DIR / _clean_device_id(device_id)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_manifest(device_id: str) -> dict[str, Any]:
    device_id = _clean_device_id(device_id)
    path = _device_dir(device_id) / 'manifest.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise OtaError(f'manifest inválido: {exc}') from exc
    filename = str(data.get('filename') or '')
    binary = _device_dir(device_id) / filename
    if data.get('device_id') != device_id or data.get('version') != '1.0.51':
        raise OtaError('identidad o versión incorrecta en manifest')
    if not filename.endswith('.bin') or '/' in filename or '\\' in filename or not binary.is_file():
        raise OtaError('binario del manifest no encontrado')
    actual_size = binary.stat().st_size
    actual_hash = _sha256(binary)
    if int(data.get('size_bytes') or 0) != actual_size or str(data.get('sha256') or '').upper() != actual_hash:
        raise OtaError('tamaño o SHA-256 no coincide con el binario')
    return {**data, 'size_bytes': actual_size, 'sha256': actual_hash}


def firmware_file_path(device_id: str, filename: str) -> Path:
    manifest = load_manifest(device_id)
    if filename != manifest['filename']:
        raise OtaError('archivo no corresponde al manifest activo')
    return _device_dir(device_id) / filename


def _server_port() -> int:
    return get_selected_ui_port()


def _local_ip_for_target(host: str) -> str:
    target = host.split(':', 1)[0]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(1.0)
        sock.connect((target, 80))
        return str(sock.getsockname()[0])


def firmware_url_for_device(device_id: str, host: str) -> str:
    manifest = load_manifest(device_id)
    return (
        f'http://{_local_ip_for_target(host)}:{_server_port()}/firmware/'
        f'{quote(device_id)}/{quote(manifest["filename"])}'
    )


async def start_device_ota(device_id: str, *, force_same_version: bool = False) -> dict[str, Any]:
    active = await ensure_device_active(device_id)
    if not active:
        return {'ok': False, 'error': 'dispositivo no activo'}
    host = str(active['host'])
    manifest = load_manifest(device_id)
    current = str((active.get('status') or {}).get('firmware_version') or '')
    if current == manifest['version'] and not force_same_version:
        return {'ok': False, 'error': 'misma versión; usa force_same_version para reinstalar', 'current_version': current}
    payload = {
        'device_id': device_id,
        'version': manifest['version'],
        'firmware_url': firmware_url_for_device(device_id, host),
        'sha256': manifest['sha256'],
    }
    response = await start_ota_update(host, payload, timeout=8.0)
    return {'ok': bool(response.get('ok')), 'device_id': device_id, 'host': host, 'previous_version': current,
            'payload': payload, 'response': response.get('data'), 'error': None if response.get('ok') else response.get('data')}


async def ota_status(device_id: str) -> dict[str, Any]:
    active = await ensure_device_active(device_id)
    if not active:
        return {'ok': False, 'error': 'dispositivo no activo'}
    return await fetch_ota_status(str(active['host']), timeout=3.0)
