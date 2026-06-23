import os
from pathlib import Path

APP_NAME = 'EcoSensor Servidor'
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / 'static'

_DATA_DIR_OVERRIDE = os.getenv('ECOSENSOR_DATA_DIR')
DATA_DIR = Path(_DATA_DIR_OVERRIDE) if _DATA_DIR_OVERRIDE else APP_DIR / 'data'

DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('NICEGUI_STORAGE_PATH', str(DATA_DIR / '.nicegui'))

SETTINGS_FILE = DATA_DIR / 'settings.json'
MEASUREMENTS_DB_FILE = DATA_DIR / 'measurements.sqlite3'

DEVICE_ID = 'ecosensor01'
UI_HOST = os.getenv('ECOSENSOR_SERVER_HOST', '0.0.0.0')
UI_PORT = int(os.getenv('ECOSENSOR_SERVER_PORT', '8765'))
MDNS_HOSTNAME = os.getenv('ECOSENSOR_MDNS_HOSTNAME', 'ecosensor')
MDNS_SERVICE_TYPE = '_http._tcp.local.'
DISABLE_MDNS = os.getenv('ECOSENSOR_DISABLE_MDNS', '').strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
SHOW_PROBE_FAILURES = os.getenv('ECOSENSOR_SHOW_PROBE_FAILURES', '').strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
LOCAL_TIMEZONE = os.getenv('ECOSENSOR_TIMEZONE', '').strip()

DEFAULT_ESP_HOST = f'{DEVICE_ID}.local'

DEFAULT_SETTINGS = {
    'esp_host': DEFAULT_ESP_HOST,
    'esp_hosts': [DEFAULT_ESP_HOST],
    'device_hosts': {DEVICE_ID: DEFAULT_ESP_HOST},
    'device_id': DEVICE_ID,
}
