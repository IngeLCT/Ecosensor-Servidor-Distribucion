import json
from copy import deepcopy
from typing import Any

from config import DATA_DIR, DEFAULT_SETTINGS, SETTINGS_FILE


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    ensure_data_dir()
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return deepcopy(DEFAULT_SETTINGS)

    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        stored = {}

    settings = deepcopy(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in stored.items() if k in settings})
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    ensure_data_dir()
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding='utf-8')
