"""Compatibilidad de asyncio en Windows.

Algunos cierres de socket del ESP32 pueden llegar como `ConnectionResetError`
desde callbacks internos de asyncio/Proactor en Windows. No afectan la lectura ya
realizada, pero ensucian la consola. Este módulo fuerza Selector cuando todavía
es posible y silencia solo ese caso puntual si el loop ya existe.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any


def install_windows_selector_policy() -> None:
    """Usa SelectorEventLoop en Windows antes de que se cree el event loop."""
    if sys.platform.startswith('win') and hasattr(asyncio, 'WindowsSelectorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _is_ignorable_connection_reset(context: dict[str, Any]) -> bool:
    exc = context.get('exception')
    if not isinstance(exc, ConnectionResetError):
        return False

    message = str(context.get('message') or '')
    handle = str(context.get('handle') or '')
    return (
        '_ProactorBasePipeTransport._call_connection_lost' in handle
        or '_call_connection_lost' in handle
        or 'connection_lost' in message.lower()
    )


def install_connection_reset_filter() -> None:
    """Silencia solo el callback benigno de cierre de socket en Windows."""
    if not sys.platform.startswith('win'):
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    previous_handler = loop.get_exception_handler()

    def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if _is_ignorable_connection_reset(context):
            return
        if previous_handler is not None:
            previous_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
