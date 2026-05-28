"""Ajustes tempranos para ejecución local en Windows.

Python importa `sitecustomize` automáticamente si el directorio del proyecto está
en `sys.path`. Esto ayuda cuando el servidor se arranca desde PyCharm o uvicorn y
el event loop se crea antes de importar `main.py`.
"""

try:
    from services.windows_asyncio import install_windows_selector_policy

    install_windows_selector_policy()
except Exception:
    # No debe impedir el arranque del servidor.
    pass
