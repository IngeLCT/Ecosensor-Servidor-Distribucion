import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, REVERSE_GEOCODING_ENDPOINT, REVERSE_GEOCODING_PRECISION, REVERSE_GEOCODING_TIMEOUT_SECONDS

CACHE_DB_FILE = DATA_DIR / 'geocoding_cache.sqlite3'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS geocoding_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL DEFAULT 'geoapify',
    lat_key REAL NOT NULL,
    lon_key REAL NOT NULL,
    label TEXT,
    formatted TEXT,
    city TEXT,
    suburb TEXT,
    district TEXT,
    municipality TEXT,
    county TEXT,
    state TEXT,
    country TEXT,
    postcode TEXT,
    result_lat REAL,
    result_lon REAL,
    source TEXT,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, lat_key, lon_key)
);
'''


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _precision() -> int:
    try:
        return max(0, min(6, int(REVERSE_GEOCODING_PRECISION)))
    except (TypeError, ValueError):
        return 4


def coordinate_key(lat: float, lon: float) -> tuple[float, float]:
    precision = _precision()
    return round(float(lat), precision), round(float(lon), precision)


def fallback_label(lat: float, lon: float) -> str:
    precision = _precision()
    lat_key, lon_key = coordinate_key(lat, lon)
    return f'{lat_key:.{precision}f}, {lon_key:.{precision}f}'


def ensure_geocoding_cache() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB_FILE) as conn:
        conn.executescript(SCHEMA)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_geocoding_cache_lat_lon ON geocoding_cache(lat_key, lon_key)')


def _row_to_result(row: sqlite3.Row | None, lat: float, lon: float) -> dict[str, Any] | None:
    if row is None:
        return None
    label = str(row['label'] or '').strip() or fallback_label(lat, lon)
    return {
        'ok': True,
        'source': row['source'] or 'local_cache',
        'provider': row['provider'] or 'geoapify',
        'label': label,
        'formatted': row['formatted'],
        'city': row['city'],
        'suburb': row['suburb'],
        'district': row['district'],
        'municipality': row['municipality'],
        'county': row['county'],
        'state': row['state'],
        'country': row['country'],
        'postcode': row['postcode'],
        'lat': row['result_lat'],
        'lon': row['result_lon'],
        'lat_key': row['lat_key'],
        'lon_key': row['lon_key'],
        'cached_locally': True,
    }


def get_cached_location(lat: float, lon: float) -> dict[str, Any] | None:
    ensure_geocoding_cache()
    lat_key, lon_key = coordinate_key(lat, lon)
    with sqlite3.connect(CACHE_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''
            SELECT * FROM geocoding_cache
            WHERE provider = 'geoapify' AND lat_key = ? AND lon_key = ?
            LIMIT 1
            ''',
            (lat_key, lon_key),
        ).fetchone()
    return _row_to_result(row, lat, lon)


def save_location(lat: float, lon: float, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_geocoding_cache()
    lat_key, lon_key = coordinate_key(lat, lon)
    location = payload.get('location') if isinstance(payload.get('location'), dict) else {}
    now = _now_iso()
    label = str(location.get('label') or '').strip() or fallback_label(lat, lon)
    values = {
        'provider': str(payload.get('provider') or 'geoapify'),
        'lat_key': lat_key,
        'lon_key': lon_key,
        'label': label,
        'formatted': location.get('formatted'),
        'city': location.get('city'),
        'suburb': location.get('suburb'),
        'district': location.get('district'),
        'municipality': location.get('municipality'),
        'county': location.get('county'),
        'state': location.get('state'),
        'country': location.get('country'),
        'postcode': location.get('postcode'),
        'result_lat': location.get('lat'),
        'result_lon': location.get('lon'),
        'source': str(payload.get('source') or 'remote'),
        'raw_json': json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
        'created_at': now,
        'updated_at': now,
    }
    with sqlite3.connect(CACHE_DB_FILE) as conn:
        conn.execute(
            '''
            INSERT INTO geocoding_cache
                (provider, lat_key, lon_key, label, formatted, city, suburb, district, municipality,
                 county, state, country, postcode, result_lat, result_lon, source, raw_json, created_at, updated_at)
            VALUES
                (:provider, :lat_key, :lon_key, :label, :formatted, :city, :suburb, :district, :municipality,
                 :county, :state, :country, :postcode, :result_lat, :result_lon, :source, :raw_json, :created_at, :updated_at)
            ON CONFLICT(provider, lat_key, lon_key) DO UPDATE SET
                label = excluded.label,
                formatted = excluded.formatted,
                city = excluded.city,
                suburb = excluded.suburb,
                district = excluded.district,
                municipality = excluded.municipality,
                county = excluded.county,
                state = excluded.state,
                country = excluded.country,
                postcode = excluded.postcode,
                result_lat = excluded.result_lat,
                result_lon = excluded.result_lon,
                source = excluded.source,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            ''',
            values,
        )
        conn.commit()
    result = get_cached_location(lat, lon)
    return result or {'ok': True, 'label': label, 'lat_key': lat_key, 'lon_key': lon_key, 'cached_locally': True}


def fetch_remote_location(lat: float, lon: float) -> dict[str, Any] | None:
    endpoint = str(REVERSE_GEOCODING_ENDPOINT or '').strip()
    if not endpoint:
        return None

    query = urllib.parse.urlencode({'lat': f'{float(lat):.6f}', 'lon': f'{float(lon):.6f}'})
    separator = '&' if '?' in endpoint else '?'
    url = f'{endpoint}{separator}{query}'
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'EcoSensor-Servidor/1.0'})

    try:
        with urllib.request.urlopen(request, timeout=float(REVERSE_GEOCODING_TIMEOUT_SECONDS)) as response:
            if response.status != 200:
                return None
            raw = response.read(1024 * 1024).decode('utf-8', errors='replace')
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict) or not payload.get('ok'):
        return None
    return save_location(lat, lon, payload)


def resolve_location(lat: float, lon: float) -> dict[str, Any]:
    cached = get_cached_location(lat, lon)
    if cached:
        return cached
    remote = fetch_remote_location(lat, lon)
    if remote:
        return remote
    lat_key, lon_key = coordinate_key(lat, lon)
    return {
        'ok': False,
        'label': fallback_label(lat, lon),
        'lat_key': lat_key,
        'lon_key': lon_key,
        'cached_locally': False,
    }


def resolve_unique_locations(points: list[tuple[float, float]]) -> dict[tuple[float, float], dict[str, Any]]:
    results: dict[tuple[float, float], dict[str, Any]] = {}
    for lat, lon in points:
        key = coordinate_key(lat, lon)
        if key in results:
            continue
        results[key] = resolve_location(lat, lon)
    return results
