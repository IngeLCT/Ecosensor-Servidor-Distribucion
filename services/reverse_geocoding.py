import json
import logging
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    DATA_DIR,
    GEOCODING_ACCEPT_LANGUAGE,
    GEOCODING_CACHE_DB,
    GEOCODING_CACHE_PRECISION,
    GEOCODING_DEFAULT_ZOOM,
    GEOCODING_ENABLE_REMOTE_LOOKUP,
    NOMINATIM_BASE_URL,
    NOMINATIM_MIN_SECONDS_BETWEEN_REQUESTS,
    NOMINATIM_TIMEOUT_SECONDS,
    NOMINATIM_USER_AGENT,
    REVERSE_GEOCODING_PROVIDER,
)

LOGGER = logging.getLogger(__name__)
PROVIDER = 'nominatim'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS reverse_geocoding_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL DEFAULT 'nominatim',
    lat_key REAL NOT NULL,
    lon_key REAL NOT NULL,
    original_lat REAL,
    original_lon REAL,
    label TEXT,
    formatted TEXT,
    city TEXT,
    suburb TEXT,
    district TEXT,
    neighbourhood TEXT,
    municipality TEXT,
    county TEXT,
    state TEXT,
    country TEXT,
    postcode TEXT,
    result_lat REAL,
    result_lon REAL,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, lat_key, lon_key)
);
'''

_rate_limit_lock = threading.Lock()
_last_request_time = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _precision() -> int:
    try:
        return max(0, min(6, int(GEOCODING_CACHE_PRECISION)))
    except (TypeError, ValueError):
        return 4


def _cache_db_path() -> Path:
    configured = Path(str(GEOCODING_CACHE_DB or 'data/geocoding_cache.sqlite3'))
    if configured.is_absolute():
        return configured
    if configured.parts and configured.parts[0] == 'data':
        return DATA_DIR / Path(*configured.parts[1:])
    return DATA_DIR / configured


def coordinate_key(lat: float, lon: float) -> tuple[float, float]:
    precision = _precision()
    return round(float(lat), precision), round(float(lon), precision)


def fallback_label(lat: float, lon: float) -> str:
    precision = _precision()
    lat_key, lon_key = coordinate_key(lat, lon)
    return f'{lat_key:.{precision}f}, {lon_key:.{precision}f}'


def _fallback_result(lat: float, lon: float, error: str | None = None) -> dict[str, Any]:
    if not _valid_lat_lon(lat, lon):
        lat_key, lon_key = None, None
        label = 'Coordenada inválida'
    else:
        try:
            lat_key, lon_key = coordinate_key(lat, lon)
            label = fallback_label(lat, lon)
        except (TypeError, ValueError, OverflowError):
            lat_key, lon_key = None, None
            label = 'Coordenada inválida'
    result: dict[str, Any] = {
        'ok': False,
        'source': 'fallback',
        'provider': PROVIDER,
        'lat_key': lat_key,
        'lon_key': lon_key,
        'label': label,
        'formatted': None,
        'city': None,
        'suburb': None,
        'district': None,
        'neighbourhood': None,
        'municipality': None,
        'county': None,
        'state': None,
        'country': None,
        'postcode': None,
        'raw': None,
        'cached_locally': False,
    }
    if error:
        result['error'] = error
    return result


def _valid_lat_lon(lat: float, lon: float) -> bool:
    try:
        lat_value = float(lat)
        lon_value = float(lon)
    except (TypeError, ValueError):
        return False
    return -90 <= lat_value <= 90 and -180 <= lon_value <= 180


def ensure_reverse_geocoding_cache() -> None:
    db_path = _cache_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_reverse_geocoding_cache_lat_lon '
            'ON reverse_geocoding_cache(provider, lat_key, lon_key)'
        )


def _decode_raw_json(raw_json: str | None) -> dict[str, Any] | None:
    if not raw_json:
        return None
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _row_to_result(row: sqlite3.Row | None, lat: float, lon: float) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        'ok': True,
        'source': 'cache',
        'provider': row['provider'] or PROVIDER,
        'lat_key': row['lat_key'],
        'lon_key': row['lon_key'],
        'label': str(row['label'] or '').strip() or fallback_label(lat, lon),
        'formatted': row['formatted'],
        'city': row['city'],
        'suburb': row['suburb'],
        'district': row['district'],
        'neighbourhood': row['neighbourhood'],
        'municipality': row['municipality'],
        'county': row['county'],
        'state': row['state'],
        'country': row['country'],
        'postcode': row['postcode'],
        'lat': row['result_lat'],
        'lon': row['result_lon'],
        'raw': _decode_raw_json(row['raw_json']),
        'cached_locally': True,
    }


def get_cached_location(lat: float, lon: float) -> dict[str, Any] | None:
    if not _valid_lat_lon(lat, lon):
        return None
    ensure_reverse_geocoding_cache()
    lat_key, lon_key = coordinate_key(lat, lon)
    with sqlite3.connect(_cache_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''
            SELECT * FROM reverse_geocoding_cache
            WHERE provider = ? AND lat_key = ? AND lon_key = ?
            LIMIT 1
            ''',
            (PROVIDER, lat_key, lon_key),
        ).fetchone()
    return _row_to_result(row, lat, lon)


def _clean_text(value: Any) -> str | None:
    text = str(value or '').strip()
    return text or None


def _pick_address(address: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _clean_text(address.get(key))
        if value:
            return value
    return None


def _build_label(address: dict[str, Any], lat_key: float, lon_key: float) -> str:
    city = _pick_address(address, 'city')
    town = _pick_address(address, 'town')
    village = _pick_address(address, 'village')
    municipality = _pick_address(address, 'municipality')
    county = _pick_address(address, 'county')
    state = _pick_address(address, 'state')
    country = _pick_address(address, 'country')
    suburb = _pick_address(address, 'suburb')
    neighbourhood = _pick_address(address, 'neighbourhood', 'quarter')
    district = _pick_address(address, 'city_district', 'district')

    candidates = [
        (city, suburb),
        (city, neighbourhood),
        (city, district),
        (town, suburb),
        (town, neighbourhood),
        (village, suburb),
        (municipality, suburb),
        (municipality, neighbourhood),
    ]
    for base, detail in candidates:
        if base and detail and detail != base:
            return f'{base} ({detail})'

    comma_candidates = [
        (city, state),
        (town, state),
        (municipality, state),
        (county, state),
        (state, country),
    ]
    for first, second in comma_candidates:
        if first and second and first != second:
            return f'{first}, {second}'
        if first:
            return first

    precision = _precision()
    return f'{lat_key:.{precision}f}, {lon_key:.{precision}f}'


def _normalise_nominatim_response(payload: dict[str, Any], lat: float, lon: float) -> dict[str, Any]:
    lat_key, lon_key = coordinate_key(lat, lon)
    address = payload.get('address') if isinstance(payload.get('address'), dict) else {}
    result_lat = None
    result_lon = None
    try:
        result_lat = float(payload.get('lat')) if payload.get('lat') is not None else None
        result_lon = float(payload.get('lon')) if payload.get('lon') is not None else None
    except (TypeError, ValueError):
        result_lat = None
        result_lon = None

    suburb = _pick_address(address, 'suburb')
    neighbourhood = _pick_address(address, 'neighbourhood', 'quarter')
    district = _pick_address(address, 'city_district', 'district')
    city = _pick_address(address, 'city', 'town', 'village', 'hamlet')

    return {
        'ok': True,
        'source': PROVIDER,
        'provider': PROVIDER,
        'lat_key': lat_key,
        'lon_key': lon_key,
        'label': _build_label(address, lat_key, lon_key),
        'formatted': _clean_text(payload.get('display_name')),
        'city': city,
        'suburb': suburb,
        'district': district,
        'neighbourhood': neighbourhood,
        'municipality': _pick_address(address, 'municipality'),
        'county': _pick_address(address, 'county'),
        'state': _pick_address(address, 'state'),
        'country': _pick_address(address, 'country'),
        'postcode': _pick_address(address, 'postcode'),
        'lat': result_lat,
        'lon': result_lon,
        'raw': payload,
        'cached_locally': False,
    }


def save_location(lat: float, lon: float, result: dict[str, Any]) -> dict[str, Any]:
    ensure_reverse_geocoding_cache()
    lat_key, lon_key = coordinate_key(lat, lon)
    now = _now_iso()
    values = {
        'provider': PROVIDER,
        'lat_key': lat_key,
        'lon_key': lon_key,
        'original_lat': float(lat),
        'original_lon': float(lon),
        'label': result.get('label') or fallback_label(lat, lon),
        'formatted': result.get('formatted'),
        'city': result.get('city'),
        'suburb': result.get('suburb'),
        'district': result.get('district'),
        'neighbourhood': result.get('neighbourhood'),
        'municipality': result.get('municipality'),
        'county': result.get('county'),
        'state': result.get('state'),
        'country': result.get('country'),
        'postcode': result.get('postcode'),
        'result_lat': result.get('lat'),
        'result_lon': result.get('lon'),
        'raw_json': json.dumps(result.get('raw') or {}, ensure_ascii=False, separators=(',', ':')),
        'created_at': now,
        'updated_at': now,
    }
    with sqlite3.connect(_cache_db_path()) as conn:
        conn.execute(
            '''
            INSERT INTO reverse_geocoding_cache
                (provider, lat_key, lon_key, original_lat, original_lon, label, formatted, city,
                 suburb, district, neighbourhood, municipality, county, state, country, postcode,
                 result_lat, result_lon, raw_json, created_at, updated_at)
            VALUES
                (:provider, :lat_key, :lon_key, :original_lat, :original_lon, :label, :formatted, :city,
                 :suburb, :district, :neighbourhood, :municipality, :county, :state, :country, :postcode,
                 :result_lat, :result_lon, :raw_json, :created_at, :updated_at)
            ON CONFLICT(provider, lat_key, lon_key) DO UPDATE SET
                original_lat = excluded.original_lat,
                original_lon = excluded.original_lon,
                label = excluded.label,
                formatted = excluded.formatted,
                city = excluded.city,
                suburb = excluded.suburb,
                district = excluded.district,
                neighbourhood = excluded.neighbourhood,
                municipality = excluded.municipality,
                county = excluded.county,
                state = excluded.state,
                country = excluded.country,
                postcode = excluded.postcode,
                result_lat = excluded.result_lat,
                result_lon = excluded.result_lon,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            ''',
            values,
        )
        conn.commit()
    saved = dict(result)
    saved['source'] = PROVIDER
    saved['cached_locally'] = True
    return saved


def _wait_for_rate_limit() -> None:
    global _last_request_time
    try:
        min_seconds = max(1.0, float(NOMINATIM_MIN_SECONDS_BETWEEN_REQUESTS))
    except (TypeError, ValueError):
        min_seconds = 1.1
    with _rate_limit_lock:
        elapsed = time.monotonic() - _last_request_time
        if elapsed < min_seconds:
            time.sleep(min_seconds - elapsed)
        _last_request_time = time.monotonic()


def _nominatim_url(lat: float, lon: float) -> str:
    query = urllib.parse.urlencode({
        'lat': f'{float(lat):.6f}',
        'lon': f'{float(lon):.6f}',
        'format': 'jsonv2',
        'addressdetails': 1,
        'accept-language': str(GEOCODING_ACCEPT_LANGUAGE or 'es'),
        'zoom': int(GEOCODING_DEFAULT_ZOOM or 14),
        'layer': 'address',
    })
    separator = '&' if '?' in str(NOMINATIM_BASE_URL) else '?'
    return f'{NOMINATIM_BASE_URL}{separator}{query}'


def fetch_nominatim_location(lat: float, lon: float) -> dict[str, Any]:
    if not GEOCODING_ENABLE_REMOTE_LOOKUP:
        return _fallback_result(lat, lon, 'Remote lookup deshabilitado.')
    if str(REVERSE_GEOCODING_PROVIDER or PROVIDER).lower() != PROVIDER:
        return _fallback_result(lat, lon, f'Proveedor no soportado: {REVERSE_GEOCODING_PROVIDER}')
    if not _valid_lat_lon(lat, lon):
        return _fallback_result(lat, lon, 'Coordenada inválida.')

    _wait_for_rate_limit()
    request = urllib.request.Request(
        _nominatim_url(lat, lon),
        headers={
            'User-Agent': str(NOMINATIM_USER_AGENT),
            'Accept': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=float(NOMINATIM_TIMEOUT_SECONDS)) as response:
            if response.status != 200:
                return _fallback_result(lat, lon, f'Nominatim respondió HTTP {response.status}.')
            raw = response.read(1024 * 1024).decode('utf-8', errors='replace')
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        LOGGER.warning('No se pudo consultar Nominatim: %s', exc)
        return _fallback_result(lat, lon, str(exc))

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _fallback_result(lat, lon, f'Respuesta JSON inválida: {exc}')
    if not isinstance(payload, dict) or payload.get('error'):
        return _fallback_result(lat, lon, str(payload.get('error') if isinstance(payload, dict) else 'Respuesta inválida.'))
    return _normalise_nominatim_response(payload, lat, lon)


def reverse_geocode_cached(lat: float, lon: float, *, allow_remote: bool = True) -> dict[str, Any]:
    if not _valid_lat_lon(lat, lon):
        return _fallback_result(lat, lon, 'Coordenada inválida.')

    cached = get_cached_location(lat, lon)
    if cached:
        return cached
    if not allow_remote:
        return _fallback_result(lat, lon, 'Límite de consultas remotas alcanzado para esta carga.')

    result = fetch_nominatim_location(lat, lon)
    if result.get('ok'):
        return save_location(lat, lon, result)
    return result


def resolve_unique_locations(
    points: list[tuple[float, float]],
    *,
    max_remote_lookups: int | None = None,
) -> dict[tuple[float, float], dict[str, Any]]:
    results: dict[tuple[float, float], dict[str, Any]] = {}
    remote_lookups = 0
    remote_limit = max_remote_lookups if max_remote_lookups is not None else 0

    for lat, lon in points:
        try:
            key = coordinate_key(lat, lon)
        except (TypeError, ValueError, OverflowError):
            continue
        if key in results:
            continue

        cached = get_cached_location(lat, lon)
        if cached:
            results[key] = cached
            continue

        allow_remote = remote_limit < 0 or remote_lookups < remote_limit
        result = reverse_geocode_cached(lat, lon, allow_remote=allow_remote)
        if result.get('source') == PROVIDER:
            remote_lookups += 1
        results[key] = result
    return results
