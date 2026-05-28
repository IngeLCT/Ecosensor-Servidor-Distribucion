from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import DATA_DIR

_LOGGER_NAME = 'ecosensor_servidor'
_configured = False


def get_logger() -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s')

    file_handler = RotatingFileHandler(
        DATA_DIR / 'ecosensor-servidor.log',
        maxBytes=1_000_000,
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    _configured = True
    logger.info('logging iniciado; archivo=%s', DATA_DIR / 'ecosensor-servidor.log')
    return logger
