"""Control de la ventana local principal del servidor portable.

La app abre una URL local con token de un solo proceso. La primera página marca
esa pestaña en ``app.storage.tab`` como principal, de modo que al navegar a otras
páginas se conserva la identidad aunque el token ya no esté en la URL.

Si el cliente principal desaparece, se espera una ventana corta antes de apagar:
esto evita cerrar el servidor durante navegación, recarga o reconexión normal.
"""

import asyncio
import secrets
import webbrowser

from fastapi import Request
from nicegui import Client, app

from config import UI_PORT

MAIN_WINDOW_TOKEN = secrets.token_urlsafe(24)
MAIN_WINDOW_TAB_KEY = 'ecosensor_es_pestana_principal'
MAIN_WINDOW_SHUTDOWN_DELAY_SECONDS = 2.5
HEAVY_PAGE_SHUTDOWN_DELAY_SECONDS = 30.0
_LOCAL_HOSTNAMES = {'127.0.0.1', 'localhost'}
_active_main_client_ids: set[str] = set()
_main_client_shutdown_delays: dict[str, float] = {}
_shutdown_task: asyncio.Task | None = None
_shutdown_started = False


def is_main_window_request(request: Request) -> bool:
    """Devuelve True solo para la pestaña local abierta con el token principal."""
    return (
        request.url.hostname in _LOCAL_HOSTNAMES
        and request.query_params.get('main') == MAIN_WINDOW_TOKEN
    )


def _cancel_pending_shutdown() -> None:
    global _shutdown_task

    if _shutdown_task and not _shutdown_task.done():
        _shutdown_task.cancel()
    _shutdown_task = None


def _schedule_shutdown_if_main_does_not_return(delay_seconds: float = MAIN_WINDOW_SHUTDOWN_DELAY_SECONDS) -> None:
    global _shutdown_task

    _cancel_pending_shutdown()
    _shutdown_task = asyncio.create_task(_shutdown_if_no_main_client(delay_seconds))


async def _shutdown_if_no_main_client(delay_seconds: float) -> None:
    global _shutdown_started

    try:
        await asyncio.sleep(delay_seconds)
        if not _active_main_client_ids and not _shutdown_started:
            _shutdown_started = True
            print('La pestaña principal se cerró. Apagando servidor NiceGUI...', flush=True)
            app.shutdown()
    except asyncio.CancelledError:
        pass


def _main_client_deleted(client_id: str) -> None:
    delay_seconds = _main_client_shutdown_delays.pop(client_id, MAIN_WINDOW_SHUTDOWN_DELAY_SECONDS)
    _active_main_client_ids.discard(client_id)
    if not _active_main_client_ids:
        _schedule_shutdown_if_main_does_not_return(delay_seconds)


async def register_main_window(
    request: Request,
    client: Client,
    *,
    shutdown_delay_seconds: float = MAIN_WINDOW_SHUTDOWN_DELAY_SECONDS,
) -> bool:
    """Registra la pestaña principal y conserva esa marca entre páginas.

    Algunos chequeos HTTP simples (por ejemplo ``curl``) pueden renderizar una
    página NiceGUI sin una conexión de cliente completa. En ese caso
    ``app.storage.tab`` no existe y no debe generar una excepción en logs.
    """
    try:
        await client.connected(timeout=1.0)
    except TimeoutError:
        # Cliente HTTP no interactivo: NiceGUI todavía puede devolver HTML, pero
        # no hay WebSocket ni storage de pestaña para registrar ventana principal.
        return False
    except Exception as exc:
        print(f'No se pudo registrar la pestaña principal: cliente no conectado ({exc})', flush=True)
        return False

    try:
        if is_main_window_request(request):
            app.storage.tab[MAIN_WINDOW_TAB_KEY] = True

        if not app.storage.tab.get(MAIN_WINDOW_TAB_KEY, False):
            return False
    except RuntimeError as exc:
        if 'app.storage.tab' not in str(exc):
            raise
        print('Solicitud HTTP sin pestaña NiceGUI; se omite registro de ventana principal.', flush=True)
        return False

    _active_main_client_ids.add(client.id)
    _main_client_shutdown_delays[client.id] = max(MAIN_WINDOW_SHUTDOWN_DELAY_SECONDS, float(shutdown_delay_seconds))
    _cancel_pending_shutdown()
    client.on_delete(lambda: _main_client_deleted(client.id))
    return True


def shutdown_if_main_window(client: Client) -> None:
    """Compatibilidad: fuerza apagado si el cliente principal desaparece."""
    global _shutdown_started

    if client.id not in _active_main_client_ids or _shutdown_started:
        return

    _active_main_client_ids.discard(client.id)
    _main_client_shutdown_delays.pop(client.id, None)
    _shutdown_started = True
    print('Se cerró la pestaña principal. Apagando servidor NiceGUI...', flush=True)
    app.shutdown()


def open_main_browser() -> None:
    """Abre la ventana principal local con token privado del proceso."""
    webbrowser.open(f'http://127.0.0.1:{UI_PORT}/dashboard?main={MAIN_WINDOW_TOKEN}')
