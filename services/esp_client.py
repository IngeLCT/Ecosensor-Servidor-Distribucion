import asyncio
import json
import re
import socket
import subprocess
from datetime import datetime
from typing import Any

from config import UI_PORT
from shared.time_utils import server_local_now, server_local_now_naive
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


TIME_DRIFT_SYNC_THRESHOLD_SECONDS = 10 * 60


def normalize_host_input(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return ''

    if '://' not in value:
        value = f'http://{value}'

    parsed = urlparse(value)
    host = parsed.netloc or parsed.path
    host = host.strip().rstrip('/')

    if '/' in host:
        host = host.split('/')[0]

    return host


def build_base_url(host: str) -> str:
    return f'http://{host}' if host else ''


def build_endpoints(host: str) -> dict[str, str]:
    base_url = build_base_url(host)
    return {
        'base_url': base_url,
        'status': f'{base_url}/status' if base_url else '',
        'lecturas': f'{base_url}/lecturas' if base_url else '',
        'lecturas_since': f'{base_url}/lecturas/since' if base_url else '',
        'lecturas_range': f'{base_url}/lecturas/range' if base_url else '',
        'lecturas_export': f'{base_url}/lecturas/export' if base_url else '',
        'lecturas_recent': f'{base_url}/lecturas/recent' if base_url else '',
        'config': f'{base_url}/config' if base_url else '',
        'time': f'{base_url}/time' if base_url else '',
        'wifi_clear': f'{base_url}/wifi/clear' if base_url else '',
        'readings_clear': f'{base_url}/lecturas/clear' if base_url else '',
    }


def fetch_json_sync(url: str, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(url, headers={'Accept': 'application/json'})
    return request_json_sync(request, url, timeout)


def delete_json_sync(url: str, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(url, headers={'Accept': 'application/json'}, method='DELETE')
    return request_json_sync(request, url, timeout)


def post_json_sync(url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    body = json.dumps(payload).encode('utf-8')
    request = Request(
        url,
        data=body,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
        method='POST',
    )
    return request_json_sync(request, url, timeout)


def request_json_sync(request: Request, url: str, timeout: float = 8.0) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', errors='replace')
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
            return {'ok': 200 <= response.status < 300, 'status': response.status, 'url': url, 'data': data}
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
        return {'ok': False, 'status': exc.code, 'url': url, 'data': raw}
    except (TimeoutError, URLError, OSError) as exc:
        return {'ok': False, 'status': 0, 'url': url, 'data': str(exc)}


async def fetch_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_json_sync, url, timeout)


async def post_json(url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    return await asyncio.to_thread(post_json_sync, url, payload, timeout)


async def delete_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    return await asyncio.to_thread(delete_json_sync, url, timeout)




def candidate_hosts(saved_host: str, default_host: str) -> list[str]:
    hosts: list[str] = []
    for host in (saved_host, default_host):
        normalized = normalize_host_input(host)
        if normalized and normalized not in hosts:
            hosts.append(normalized)
    return hosts


def _strip_host_port(host: str) -> str:
    clean = normalize_host_input(host)
    if clean.startswith('[') and ']' in clean:
        return clean[1:clean.index(']')]
    return clean.rsplit(':', 1)[0] if ':' in clean and clean.count(':') == 1 else clean


def _same_ipv4_24(ip_a: str, ip_b: str) -> bool:
    try:
        a = [int(part) for part in ip_a.split('.')]
        b = [int(part) for part in ip_b.split('.')]
    except ValueError:
        return False
    return len(a) == 4 and len(b) == 4 and a[:3] == b[:3]


def _resolve_ipv4_hosts(host: str) -> list[str]:
    clean_host = _strip_host_port(host)
    if not clean_host:
        return []
    try:
        socket.inet_aton(clean_host)
        return [clean_host]
    except OSError:
        pass

    resolved: list[str] = []
    try:
        infos = socket.getaddrinfo(clean_host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    for info in infos:
        ip = str(info[4][0])
        if ip and ip not in resolved:
            resolved.append(ip)
    return resolved


def _local_ipv4_candidates() -> list[str]:
    candidates: list[str] = []

    def add(ip: str) -> None:
        if not ip or ip.startswith('127.') or ip == '0.0.0.0':
            return
        if ip not in candidates:
            candidates.append(ip)

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            add(str(info[4][0]))
    except OSError:
        pass

    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            add(str(ip))
    except OSError:
        pass

    # En Windows, gethostname/getaddrinfo no siempre lista todas las interfaces
    # activas. Como el instalador/servidor es local, usar ipconfig como respaldo
    # evita enviar la IP de otra red cuando el EcoSensor está en un AP aislado.
    commands = (
        ['ipconfig'],
        ['ip', '-4', 'addr', 'show'],
        ['ifconfig'],
    )
    for command in commands:
        try:
            output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=1.5)
        except (OSError, subprocess.SubprocessError):
            continue
        for ip in re.findall(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', output):
            parts = ip.split('.')
            if all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
                add(ip)

    return candidates


def _local_ip_for_target(target_host: str) -> str | None:
    target_ips = _resolve_ipv4_hosts(target_host)
    if not target_ips:
        return None

    local_candidates = _local_ipv4_candidates()
    for target_ip in target_ips:
        for local_ip in local_candidates:
            if _same_ipv4_24(local_ip, target_ip):
                return local_ip

    # Fallback: preguntar a la tabla de rutas usando la IP ya resuelta. Esto evita
    # depender de mDNS al calcular la IP que recibirá el EcoSensor.
    for target_ip in target_ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(0.5)
                sock.connect((target_ip, 80))
                local_ip = sock.getsockname()[0]
                if local_ip and not local_ip.startswith('127.'):
                    return local_ip
        except OSError:
            continue
    return None



def _parse_device_datetime(value: Any) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None

    # En este proyecto el dashboard muestra la hora del EcoSensor en crudo
    # (por ejemplo 2026-05-28T12:27:52Z se ve como 12:27:52). Para detectar
    # desfases usamos esa misma referencia visual/local y no convertimos la Z
    # como zona UTC real.
    if text.endswith('Z'):
        text = text[:-1]
    if 'T' in text:
        text = text.replace('T', ' ', 1)
    if '+' in text:
        text = text.split('+', 1)[0]
    if len(text) > 19:
        text = text[:19]

    for fmt in ('%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _time_drift_seconds(status_data: dict[str, Any]) -> int | None:
    candidates = (
        status_data.get('current_datetime'),
        status_data.get('last_measurement_timestamp'),
    )
    drifts: list[int] = []
    now = server_local_now_naive()
    for value in candidates:
        device_dt = _parse_device_datetime(value)
        if device_dt is not None:
            drifts.append(int((now - device_dt).total_seconds()))
    if not drifts:
        return None
    return max(drifts, key=lambda item: abs(item))


def sync_time_if_needed_sync(host: str, timeout: float = 4.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    status = fetch_json_sync(endpoints['status'], timeout=timeout)
    if not status.get('ok') or not isinstance(status.get('data'), dict):
        return {'ok': False, 'host': host, 'status': status, 'synced': False}

    status_data = status['data']
    needs_sync = bool(status_data.get('needs_time_sync', not status_data.get('time_valid', False)))
    drift_s = _time_drift_seconds(status_data)
    drift_exceeded = drift_s is not None and abs(drift_s) > TIME_DRIFT_SYNC_THRESHOLD_SECONDS
    if drift_exceeded:
        needs_sync = True
    if not needs_sync:
        return {'ok': True, 'host': host, 'status': status, 'synced': False, 'time_drift_s': drift_s}

    payload = system_datetime_payload(host)
    sync_response = post_json_sync(endpoints['time'], payload, timeout=timeout)
    if not sync_response.get('ok'):
        sync_response = post_json_sync(endpoints['config'], payload, timeout=timeout)

    sync_data = sync_response.get('data')
    synced = bool(sync_response.get('ok') and isinstance(sync_data, dict) and sync_data.get('time_valid'))
    return {
        'ok': synced,
        'host': host,
        'status': status,
        'sync': sync_response,
        'synced': synced,
        'time_drift_s': drift_s,
        'forced_by_time_drift': drift_exceeded,
    }


async def sync_time_if_needed(host: str, timeout: float = 4.0) -> dict[str, Any]:
    return await asyncio.to_thread(sync_time_if_needed_sync, host, timeout)




def push_host_payload(target_host: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    server_ip = _local_ip_for_target(target_host)
    if server_ip:
        payload['push_host'] = server_ip
    return payload

def configure_push_host_sync(host: str, timeout: float = 4.0) -> dict[str, Any]:
    payload = system_datetime_payload(host)
    if 'push_host' not in payload:
        return {'ok': False, 'host': host, 'data': 'server_ip_unavailable'}
    endpoints = build_endpoints(host)
    sync_response = post_json_sync(endpoints['time'], payload, timeout=timeout)
    if not sync_response.get('ok'):
        sync_response = post_json_sync(endpoints['config'], payload, timeout=timeout)
    confirm_status = fetch_json_sync(endpoints['status'], timeout=timeout) if sync_response.get('ok') else None
    return {
        'ok': bool(sync_response.get('ok')),
        'host': host,
        'sync': sync_response,
        'status': confirm_status,
        'push_host': payload.get('push_host'),
    }


async def configure_push_host(host: str, timeout: float = 4.0) -> dict[str, Any]:
    return await asyncio.to_thread(configure_push_host_sync, host, timeout)

async def fetch_readings_since(host: str, after_id: int, limit: int = 25, timeout: float = 20.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['lecturas_since']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    query = urlencode({
        'after': max(0, int(after_id)),
        'limit': max(1, int(limit)),
        'timeout_ms': max(250, int(timeout * 1000)),
    })
    return await fetch_json(f"{endpoints['lecturas_since']}?{query}", timeout=timeout)


async def fetch_readings_range(host: str, from_id: int, to_id: int, limit: int = 25, timeout: float = 30.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['lecturas_range']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    query = urlencode({
        'from': max(1, int(from_id)),
        'to': max(1, int(to_id)),
        'limit': max(1, int(limit)),
        'timeout_ms': max(250, int(timeout * 1000)),
    })
    return await fetch_json(f"{endpoints['lecturas_range']}?{query}", timeout=timeout)


def fetch_readings_export_sync(host: str, from_id: int, to_id: int, timeout: float = 120.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['lecturas_export']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    query = urlencode({
        'from': max(1, int(from_id)),
        'to': max(1, int(to_id)),
        'timeout_ms': max(30000, int(timeout * 1000)),
    })
    url = f"{endpoints['lecturas_export']}?{query}"
    request = Request(url, headers={'Accept': 'application/x-ndjson'})
    rows: list[dict[str, Any]] = []
    errors: list[Any] = []
    try:
        with urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(line[:160])
                    continue
                if isinstance(item, dict) and 'error' in item:
                    errors.append(item)
                    continue
                if isinstance(item, dict):
                    rows.append(item)
            ok = 200 <= response.status < 300 and not errors
            return {
                'ok': ok,
                'status': response.status,
                'url': url,
                'data': {'rows': rows, 'count': len(rows), 'errors': errors},
            }
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
        return {'ok': False, 'status': exc.code, 'url': url, 'data': raw}
    except (TimeoutError, URLError, OSError) as exc:
        return {'ok': False, 'status': 0, 'url': url, 'data': str(exc)}


async def fetch_readings_export(host: str, from_id: int, to_id: int, timeout: float = 120.0) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_readings_export_sync, host, from_id, to_id, timeout)


async def fetch_recent_readings(host: str, after_id: int, before_id: int = 0, limit: int = 25, timeout: float = 4.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['lecturas_recent']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    query = urlencode({
        'after': max(0, int(after_id)),
        'before': max(0, int(before_id)),
        'limit': max(1, int(limit)),
        'timeout_ms': max(250, int(timeout * 800)),
    })
    return await fetch_json(f"{endpoints['lecturas_recent']}?{query}", timeout=timeout)


async def autoconnect_and_sync(saved_host: str, default_host: str) -> dict[str, Any]:
    last_result: dict[str, Any] = {'ok': False, 'host': '', 'synced': False}
    for host in candidate_hosts(saved_host, default_host):
        result = await sync_time_if_needed(host)
        if result.get('ok'):
            return result
        last_result = result
    return last_result


def system_datetime_payload(target_host: str | None = None) -> dict[str, str]:
    now = server_local_now()
    payload = {
        'date': now.strftime('%d-%m-%Y'),
        'time': now.strftime('%H:%M:%S'),
    }
    if target_host:
        server_ip = _local_ip_for_target(target_host)
        if server_ip:
            payload['push_host'] = server_ip
    return payload
