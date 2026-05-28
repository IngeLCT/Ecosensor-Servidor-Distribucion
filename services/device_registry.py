import asyncio
import ipaddress
import re
import socket
import subprocess
from datetime import datetime, timedelta
from time import perf_counter
from typing import Any

from config import DEFAULT_ESP_HOST, DEVICE_ID
from services.app_logging import get_logger
from services.esp_client import build_endpoints, fetch_json_sync, normalize_host_input
from shared.formatters import device_display_name
from storage.settings_store import load_settings, save_settings

# Un EcoSensor no debe desaparecer por un fallo puntual de mDNS/red.
ACTIVE_TTL_SECONDS = 300
DISCOVERY_MAX_DEVICE_NUMBER = 12
DISCOVERY_REFRESH_INTERVAL_SECONDS = 20
CONFIGURED_PROBE_TIMEOUT_SECONDS = 0.7
DISCOVERY_PROBE_TIMEOUT_SECONDS = 0.8
DISCOVERY_CONCURRENCY = 64
LAN_SCAN_ENABLED = True
LAN_SCAN_TIMEOUT_SECONDS = 0.25
_DEVICE_RE = re.compile(r'^(ecosensor\d+)(?:\.local)?(?::\d+)?$', re.IGNORECASE)
_REAL_DEVICE_RE = re.compile(r'^ecosensor(0[1-9]|1[0-2])$', re.IGNORECASE)

logger = get_logger()

_active_devices: dict[str, dict[str, Any]] = {}
_probe_failures: dict[str, dict[str, Any]] = {}
_probe_lock = asyncio.Lock()
_refresh_task: asyncio.Task | None = None
_last_refresh_at: datetime | None = None
_registry_revision = 0


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _host_port(value: str) -> tuple[str, int]:
    clean = normalize_host_input(value)
    if ':' not in clean:
        return clean, 80
    host, raw_port = clean.rsplit(':', 1)
    try:
        port = int(raw_port)
    except ValueError:
        return clean, 80
    return host, port


def _is_valid_ip(value: str) -> bool:
    host, _ = _host_port(value)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not ip.is_unspecified


def _tcp_port_open_sync(host: str, timeout: float) -> bool:
    target, port = _host_port(host)
    try:
        with socket.create_connection((target, port), timeout=timeout):
            return True
    except OSError:
        return False


async def _tcp_port_open(host: str, timeout: float) -> bool:
    return await asyncio.to_thread(_tcp_port_open_sync, host, timeout)


def _resolve_host_quick_sync(host: str, timeout: float = 0.4) -> str | None:
    target, _ = _host_port(host)
    if _is_valid_ip(target):
        return target
    try:
        result = subprocess.run(
            ['getent', 'hosts', target],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and _is_valid_ip(parts[0]):
            return parts[0]
    return None


async def _resolve_host_quick(host: str, timeout: float = 0.4) -> str | None:
    return await asyncio.to_thread(_resolve_host_quick_sync, host, timeout)


async def _async_tcp_port_open(host: str, timeout: float) -> bool:
    target, port = _host_port(host)
    writer = None
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(target, port), timeout=timeout)
        return True
    except (OSError, asyncio.TimeoutError, ConnectionResetError):
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, asyncio.TimeoutError, ConnectionResetError):
                pass


async def _scan_http_hosts(hosts: list[str], timeout: float) -> list[str]:
    semaphore = asyncio.Semaphore(128)

    async def check(host: str) -> str | None:
        async with semaphore:
            return host if await _async_tcp_port_open(host, timeout) else None

    found = await asyncio.gather(*(check(host) for host in hosts))
    return [host for host in found if host]


def _is_real_ecosensor_id(device_id: str | None) -> bool:
    return bool(_REAL_DEVICE_RE.match(str(device_id or '').strip().lower()))


def _status_device_id(status_data: dict[str, Any] | None) -> str | None:
    if not isinstance(status_data, dict):
        return None
    raw = status_data.get('device_id') or status_data.get('id')
    if raw is None:
        return None
    value = str(raw).strip().lower()
    return value if _is_real_ecosensor_id(value) else None


def _status_ip(status_data: dict[str, Any] | None) -> str | None:
    if not isinstance(status_data, dict):
        return None
    raw = str(status_data.get('ip') or '').strip()
    return raw if _is_valid_ip(raw) else None


def device_id_from_host(host: str) -> str:
    clean = normalize_host_input(host)
    if not clean:
        return ''
    base = clean.split(':', 1)[0]
    match = _DEVICE_RE.match(base)
    if match:
        candidate = match.group(1).lower()
        return candidate if _is_real_ecosensor_id(candidate) else ''
    if base.endswith('.local'):
        base = base[:-6]
    candidate = base.lower()
    return candidate if _is_real_ecosensor_id(candidate) else ''


def _settings_device_hosts(settings: dict[str, Any]) -> dict[str, str]:
    raw = settings.get('device_hosts')
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        device_id = str(key or '').strip().lower()
        host = normalize_host_input(str(value or ''))
        if _is_real_ecosensor_id(device_id) and host:
            out[device_id] = host
    return out


def host_for_device(device_id: str) -> str:
    device_id = (device_id or DEVICE_ID).strip().lower()
    settings = load_settings()
    device_hosts = _settings_device_hosts(settings)
    if device_hosts.get(device_id):
        return device_hosts[device_id]
    for host in configured_hosts():
        if device_id_from_host(host) == device_id:
            return host
    return f'{device_id}.local'


def configured_hosts() -> list[str]:
    settings = load_settings()
    hosts: list[str] = []

    # Primero IP/host conocido por device_id: es lo más rápido y evita depender de mDNS.
    for host in _settings_device_hosts(settings).values():
        if host and host not in hosts:
            hosts.append(host)

    raw_hosts = settings.get('esp_hosts')
    if isinstance(raw_hosts, list):
        for item in raw_hosts:
            host = normalize_host_input(str(item))
            if host and host not in hosts:
                hosts.append(host)
    legacy = normalize_host_input(str(settings.get('esp_host') or DEFAULT_ESP_HOST))
    if legacy and legacy not in hosts:
        hosts.append(legacy)
    default = normalize_host_input(DEFAULT_ESP_HOST)
    if default and default not in hosts:
        hosts.append(default)
    return hosts


def _local_ipv4_addresses() -> list[str]:
    addresses: list[str] = []

    # Método stdlib: detecta la IP local usada para salir a la red.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            sock.connect(('8.8.8.8', 80))
            ip = sock.getsockname()[0]
            if ip and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass

    # Método Linux: recoge todas las IPv4 activas por si hay varias interfaces.
    try:
        result = subprocess.run(
            ['ip', '-o', '-4', 'addr', 'show', 'scope', 'global'],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4 or 'inet' not in parts:
                continue
            interface = parts[1]
            if interface.startswith(('docker', 'br-', 'veth', 'tailscale', 'tun', 'wg')):
                continue
            cidr = parts[parts.index('inet') + 1]
            ip = cidr.split('/', 1)[0]
            if ip and ip not in addresses:
                addresses.append(ip)
    except (OSError, subprocess.SubprocessError):
        pass

    return addresses


def _local_subnet_hosts() -> list[str]:
    if not LAN_SCAN_ENABLED:
        return []

    hosts: list[str] = []
    for local_ip in _local_ipv4_addresses():
        try:
            address = ipaddress.ip_address(local_ip)
        except ValueError:
            continue
        if not address.is_private:
            continue
        network = ipaddress.ip_network(f'{local_ip}/24', strict=False)
        for candidate in network.hosts():
            candidate_text = str(candidate)
            if candidate_text == local_ip:
                continue
            if candidate_text not in hosts:
                hosts.append(candidate_text)
    return hosts


def discovery_hosts() -> list[str]:
    hosts = configured_hosts()
    for number in range(1, DISCOVERY_MAX_DEVICE_NUMBER + 1):
        host = f'ecosensor{number:02d}.local'
        if host not in hosts:
            hosts.append(host)
    for host in _local_subnet_hosts():
        if host not in hosts:
            hosts.append(host)
    return hosts


def registry_revision() -> int:
    return _registry_revision


def forget_device(device_id: str) -> None:
    """Quita un EcoSensor de la lista activa y de hosts recordados tras borrar WiFi."""
    global _registry_revision
    clean_device_id = (device_id or '').strip().lower()
    if not clean_device_id:
        return

    removed = _active_devices.pop(clean_device_id, None)
    settings = load_settings()
    device_hosts = _settings_device_hosts(settings)
    removed_host = device_hosts.pop(clean_device_id, None)

    raw_hosts = settings.get('esp_hosts')
    if isinstance(raw_hosts, list) and removed_host:
        settings['esp_hosts'] = [
            normalize_host_input(str(item))
            for item in raw_hosts
            if normalize_host_input(str(item)) and normalize_host_input(str(item)) != removed_host
        ]

    if settings.get('device_id') == clean_device_id:
        settings.pop('device_id', None)
    if removed_host and normalize_host_input(str(settings.get('esp_host') or '')) == removed_host:
        settings.pop('esp_host', None)

    settings['device_hosts'] = device_hosts
    save_settings(settings)

    if removed_host:
        _probe_failures.pop(removed_host, None)
    if removed is not None or removed_host is not None:
        _registry_revision += 1


def remember_host(host: str, device_id: str | None = None) -> None:
    host = normalize_host_input(host)
    if not host:
        return
    settings = load_settings()
    hosts = []
    raw_hosts = settings.get('esp_hosts')
    if isinstance(raw_hosts, list):
        hosts = [normalize_host_input(str(item)) for item in raw_hosts]
        hosts = [item for item in hosts if item]
    legacy = normalize_host_input(str(settings.get('esp_host') or ''))
    if legacy and legacy not in hosts:
        hosts.append(legacy)
    if host not in hosts:
        hosts.append(host)

    resolved_device_id = (device_id or device_id_from_host(host) or DEVICE_ID).strip().lower()
    if not _is_real_ecosensor_id(resolved_device_id):
        return
    device_hosts = _settings_device_hosts(settings)
    device_hosts[resolved_device_id] = host

    settings['esp_host'] = host
    settings['esp_hosts'] = hosts
    settings['device_hosts'] = device_hosts
    settings['device_id'] = resolved_device_id
    save_settings(settings)


def _mark_active(host: str, status_data: dict[str, Any] | None = None, device_id: str | None = None, latency_ms: int | None = None) -> dict[str, Any] | None:
    global _registry_revision
    host = normalize_host_input(host)
    resolved_device_id = (device_id or _status_device_id(status_data) or device_id_from_host(host) or DEVICE_ID).strip().lower()
    if not _is_real_ecosensor_id(resolved_device_id):
        _mark_probe_failure(host, f'device_id no permitido: {resolved_device_id}')
        return None
    previous = _active_devices.get(resolved_device_id)
    entry = {
        'device_id': resolved_device_id,
        'host': host,
        'label': resolved_device_id,
        'last_seen': _now_iso(),
        'latency_ms': latency_ms,
        'status': status_data or {},
    }
    _active_devices[resolved_device_id] = entry
    _probe_failures.pop(host, None)
    if not previous or previous.get('host') != host:
        logger.info('device_active device=%s host=%s latency_ms=%s previous_host=%s', resolved_device_id, host, latency_ms, (previous or {}).get('host'))
        _registry_revision += 1
    return entry


def mark_device_seen(device_id: str, host: str, status_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Marca un EcoSensor como activo sin hacer sondeo de red.

    Se usa cuando el dispositivo ya demostró vida enviando una medición push.
    Así el dashboard puede listar sensores disponibles inmediatamente, aunque
    el escaneo mDNS/LAN o la sincronización histórica estén corriendo aparte.
    """
    return _mark_active(host, status_data or {'device_id': device_id}, device_id)


def _summarize_probe_error(error: Any) -> str:
    text = str(error or 'sin respuesta').strip()
    lower = text.lower()
    if '<html' in lower or '<!doctype html' in lower:
        return 'responde HTTP, pero /status no es JSON de EcoSensor'
    if 'name or service not known' in lower or 'temporary failure in name resolution' in lower:
        return 'mDNS/DNS no resolvió el nombre'
    if 'timed out' in lower or 'timeout' in lower:
        return 'timeout de conexión'
    if 'connection refused' in lower or 'errno 111' in lower:
        return 'puerto 80 cerrado/rechazado'
    if '404' in lower or 'not found' in lower:
        return 'responde HTTP, pero no existe /status de EcoSensor'
    return text[:160]


def _mark_probe_failure(host: str, error: Any) -> None:
    summary = _summarize_probe_error(error)
    previous = _probe_failures.get(host, {}).get('error')
    _probe_failures[host] = {
        'host': host,
        'last_probe': _now_iso(),
        'error': summary,
    }
    if previous != summary:
        logger.warning('probe_failure host=%s error=%s', host, summary)


def _prune_expired() -> None:
    now = datetime.now()
    expired: list[str] = []
    for device_id, entry in _active_devices.items():
        try:
            last_seen = datetime.fromisoformat(str(entry.get('last_seen') or ''))
        except ValueError:
            expired.append(device_id)
            continue
        if now - last_seen > timedelta(seconds=ACTIVE_TTL_SECONDS):
            expired.append(device_id)
    for device_id in expired:
        _active_devices.pop(device_id, None)


def active_devices() -> list[dict[str, Any]]:
    _prune_expired()
    for device_id in list(_active_devices):
        if not _is_real_ecosensor_id(device_id):
            _active_devices.pop(device_id, None)
    return sorted(_active_devices.values(), key=lambda item: item.get('device_id') or '')


def active_device_options() -> dict[str, str]:
    return {item['device_id']: device_display_name(str(item['device_id'])) for item in active_devices()}


def probe_failures() -> list[dict[str, Any]]:
    return sorted(_probe_failures.values(), key=lambda item: item.get('host') or '')


def _refresh_is_stale() -> bool:
    if _last_refresh_at is None:
        return True
    return datetime.now() - _last_refresh_at > timedelta(seconds=DISCOVERY_REFRESH_INTERVAL_SECONDS)


def _schedule_refresh() -> None:
    global _refresh_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(refresh_active_devices())


async def probe_host(host: str, timeout: float = CONFIGURED_PROBE_TIMEOUT_SECONDS) -> dict[str, Any] | None:
    """Detección rápida: un sensor está activo si responde /status.

    La sincronización de hora no se usa como prueba de vida porque puede fallar
    aunque el ESP32 esté encendido y publicando lecturas.
    """
    host = normalize_host_input(host)
    if not host:
        return None

    request_host = host
    if not _is_valid_ip(host):
        resolved_ip = await _resolve_host_quick(host)
        if resolved_ip:
            request_host = resolved_ip
        elif host.endswith('.local'):
            _mark_probe_failure(host, 'mDNS no resolvió el nombre')
            return None

    if _is_valid_ip(request_host) and not await _tcp_port_open(request_host, timeout):
        _mark_probe_failure(host, 'puerto 80 cerrado o sin respuesta')
        return None

    started = perf_counter()
    status = await asyncio.to_thread(fetch_json_sync, build_endpoints(request_host)['status'], timeout)
    latency_ms = int((perf_counter() - started) * 1000)
    status_data = status.get('data') if status.get('ok') else None
    if not status.get('ok') or not isinstance(status_data, dict):
        _mark_probe_failure(host, status.get('data'))
        return None

    resolved_device_id = _status_device_id(status_data)
    if not resolved_device_id:
        raw_device_id = status_data.get('device_id') or status_data.get('id')
        _mark_probe_failure(host, f'no es EcoSensor real: device_id={raw_device_id!r}')
        return None

    reachable_host = _status_ip(status_data) or request_host
    entry = _mark_active(reachable_host, status_data, resolved_device_id, latency_ms)
    if not entry:
        return None
    remember_host(reachable_host, entry['device_id'])
    return entry


async def refresh_active_devices() -> list[dict[str, Any]]:
    global _last_refresh_at
    async with _probe_lock:
        started = perf_counter()
        configured = configured_hosts()
        configured_set = set(configured)
        direct_hosts: list[str] = []
        lan_candidates: list[str] = []
        for host in discovery_hosts():
            if _is_valid_ip(host) and host not in configured_set:
                lan_candidates.append(host)
            else:
                direct_hosts.append(host)

        open_lan_hosts = await _scan_http_hosts(lan_candidates, LAN_SCAN_TIMEOUT_SECONDS)
        all_hosts = direct_hosts + [host for host in open_lan_hosts if host not in direct_hosts]
        semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

        async def limited_probe(host: str) -> None:
            timeout = CONFIGURED_PROBE_TIMEOUT_SECONDS if host in configured_set else DISCOVERY_PROBE_TIMEOUT_SECONDS
            async with semaphore:
                await probe_host(host, timeout=timeout)

        await asyncio.gather(*(limited_probe(host) for host in all_hosts))
        _last_refresh_at = datetime.now()
        _prune_expired()
        devices = active_devices()
        logger.info(
            'discovery_refresh direct=%s lan_open=%s total_probe=%s active=%s elapsed_ms=%s',
            len(direct_hosts),
            len(open_lan_hosts),
            len(all_hosts),
            [item.get('device_id') for item in devices],
            int((perf_counter() - started) * 1000),
        )
        return devices


async def ensure_active_devices() -> list[dict[str, Any]]:
    devices = active_devices()
    if devices:
        if _refresh_is_stale():
            _schedule_refresh()
        return devices
    return await refresh_active_devices()


async def ensure_device_active(device_id: str | None) -> dict[str, Any] | None:
    target = (device_id or '').strip().lower()
    if target:
        for item in active_devices():
            if item['device_id'] == target:
                return item
        return await probe_host(host_for_device(target))
    devices = await ensure_active_devices()
    return devices[0] if devices else None
