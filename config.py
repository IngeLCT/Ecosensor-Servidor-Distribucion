import os
from pathlib import Path

APP_NAME = 'EcoSensor'
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / 'static'

_DATA_DIR_OVERRIDE = os.getenv('ECOSENSOR_DATA_DIR')

if _DATA_DIR_OVERRIDE:
    DATA_DIR = Path(_DATA_DIR_OVERRIDE)
else:
    DATA_DIR = Path(os.getenv('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'EcoSensorServidor'

DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('NICEGUI_STORAGE_PATH', str(DATA_DIR / '.nicegui'))

SETTINGS_FILE = DATA_DIR / 'settings.json'
MEASUREMENTS_DB_FILE = DATA_DIR / 'measurements.sqlite3'

REVERSE_GEOCODING_PROVIDER = os.getenv('ECOSENSOR_REVERSE_GEOCODING_PROVIDER', 'nominatim')
NOMINATIM_BASE_URL = os.getenv('ECOSENSOR_NOMINATIM_BASE_URL', 'https://nominatim.openstreetmap.org/reverse')
NOMINATIM_USER_AGENT = os.getenv(
    'ECOSENSOR_NOMINATIM_USER_AGENT',
    'EcoSensorServidor/1.0 (LCT Didacticos; contacto: ingenieria@lctdidacticos.com)',
)
NOMINATIM_TIMEOUT_SECONDS = float(os.getenv('ECOSENSOR_NOMINATIM_TIMEOUT_SECONDS', '8'))
NOMINATIM_MIN_SECONDS_BETWEEN_REQUESTS = float(os.getenv('ECOSENSOR_NOMINATIM_MIN_SECONDS_BETWEEN_REQUESTS', '1.1'))
NOMINATIM_MAX_LOOKUPS_PER_PAGE_LOAD = int(os.getenv('ECOSENSOR_NOMINATIM_MAX_LOOKUPS_PER_PAGE_LOAD', '10'))
GEOCODING_CACHE_DB = os.getenv('ECOSENSOR_GEOCODING_CACHE_DB', 'data/geocoding_cache.sqlite3')
GEOCODING_CACHE_PRECISION = int(os.getenv('ECOSENSOR_GEOCODING_CACHE_PRECISION', '4'))
GEOCODING_ENABLE_REMOTE_LOOKUP = os.getenv('ECOSENSOR_GEOCODING_ENABLE_REMOTE_LOOKUP', 'true').strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
GEOCODING_DEFAULT_ZOOM = int(os.getenv('ECOSENSOR_GEOCODING_DEFAULT_ZOOM', '14'))
GEOCODING_ACCEPT_LANGUAGE = os.getenv('ECOSENSOR_GEOCODING_ACCEPT_LANGUAGE', 'es')

DEVICE_ID = 'ecosensor01'
UI_HOST = os.getenv('ECOSENSOR_SERVER_HOST', '0.0.0.0')
UI_PORT = int(os.getenv('ECOSENSOR_SERVER_PORT', '80'))
UI_FALLBACK_PORT = int(os.getenv('ECOSENSOR_SERVER_FALLBACK_PORT', '8765'))
UI_PORT_SCAN_START = int(os.getenv('ECOSENSOR_SERVER_PORT_SCAN_START', '8766'))
UI_PORT_SCAN_END = int(os.getenv('ECOSENSOR_SERVER_PORT_SCAN_END', '8799'))
UI_PORT_CANDIDATES = [UI_PORT, UI_FALLBACK_PORT]
SELECTED_UI_PORT = UI_PORT
MDNS_HOSTNAME = os.getenv('ECOSENSOR_MDNS_HOSTNAME', 'ecosensor')
MDNS_SERVICE_TYPE = '_http._tcp.local.'
DISABLE_MDNS = os.getenv('ECOSENSOR_DISABLE_MDNS', '').strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
SHOW_PROBE_FAILURES = os.getenv('ECOSENSOR_SHOW_PROBE_FAILURES', '').strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
LOCAL_TIMEZONE = os.getenv('ECOSENSOR_TIMEZONE', '').strip()

DEFAULT_ESP_HOST = f'{DEVICE_ID}.local'


def set_selected_ui_port(port: int) -> None:
    global SELECTED_UI_PORT
    SELECTED_UI_PORT = port


def get_selected_ui_port() -> int:
    return SELECTED_UI_PORT

DEFAULT_SETTINGS = {
    'esp_host': DEFAULT_ESP_HOST,
    'esp_hosts': [DEFAULT_ESP_HOST],
    'device_hosts': {DEVICE_ID: DEFAULT_ESP_HOST},
    'device_id': DEVICE_ID,
}
