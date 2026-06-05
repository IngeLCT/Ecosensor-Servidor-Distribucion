"""Control de la ventana local principal del servidor portable.

La app abre una URL local con token de un solo proceso. La pestaña se marca como
ventana principal para identificar el arranque local, pero por defecto no apaga el
servidor al cerrarse: una recarga, navegación o desconexión del websocket de
NiceGUI también puede disparar el evento de eliminación del cliente.
"""

import os
import secrets
import webbrowser

from fastapi import Request
from nicegui import Client, app

from config import UI_PORT

MAIN_WINDOW_TOKEN = secrets.token_urlsafe(24)
SHUTDOWN_ON_MAIN_WINDOW_CLOSE = os.getenv('ECOSENSOR_SHUTDOWN_ON_MAIN_CLOSE', '').strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
_LOCAL_HOSTNAMES = {'127.0.0.1', 'localhost'}
_main_client_id: str | None = None
_shutdown_started = False


def is_main_window_request(request: Request) -> bool:
    """Devuelve True solo para la pestaña local abierta con el token principal."""
    return (
        request.url.hostname in _LOCAL_HOSTNAMES
        and request.query_params.get('main') == MAIN_WINDOW_TOKEN
    )


def register_main_window(request: Request, client: Client) -> bool:
    """Registra el cliente principal local.

    El apagado automático queda desactivado por defecto para que una recarga,
    cambio de página o fallo de vista no cierre todo el servidor.
    """
    global _main_client_id

    if not is_main_window_request(request):
        return False

    _main_client_id = client.id
    if SHUTDOWN_ON_MAIN_WINDOW_CLOSE:
        client.on_delete(lambda: shutdown_if_main_window(client))
    return True


def shutdown_if_main_window(client: Client) -> None:
    """Apaga NiceGUI si se cerró la pestaña principal y la opción está activada."""
    global _shutdown_started

    if client.id != _main_client_id or _shutdown_started:
        return

    _shutdown_started = True
    print('Se cerró la pestaña principal. Apagando servidor NiceGUI...', flush=True)
    app.shutdown()


def open_main_browser() -> None:
    """Abre la ventana principal local con token privado del proceso."""
    webbrowser.open(f'http://127.0.0.1:{UI_PORT}/dashboard?main={MAIN_WINDOW_TOKEN}')
