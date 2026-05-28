import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / 'data'
STATIC_DIR = APP_DIR / 'static'
SETTINGS_FILE = DATA_DIR / 'settings.json'
MEASUREMENTS_DB_FILE = DATA_DIR / 'measurements.sqlite3'

DEVICE_ID = 'ecosensor01'
UI_HOST = os.getenv('ECOSENSOR_SERVER_HOST', '0.0.0.0')
UI_PORT = int(os.getenv('ECOSENSOR_SERVER_PORT', '8765'))
MDNS_HOSTNAME = os.getenv('ECOSENSOR_MDNS_HOSTNAME', 'ecosensor-servidor')
MDNS_SERVICE_TYPE = '_http._tcp.local.'

DEFAULT_ESP_HOST = f'{DEVICE_ID}.local'

DEFAULT_SETTINGS = {
    'esp_host': DEFAULT_ESP_HOST,
    'esp_hosts': [DEFAULT_ESP_HOST],
    'device_hosts': {DEVICE_ID: DEFAULT_ESP_HOST},
    'device_id': DEVICE_ID,
}
