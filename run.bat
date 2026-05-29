@echo off
setlocal

cd /d "%~dp0"

echo ========================================
echo EcoSensor Servidor Portable
echo ========================================
echo.

if not exist ".\python\python.exe" (
    echo ERROR: No se encontro .\python\python.exe
    echo Ejecuta primero crear_portable.ps1 para preparar la carpeta portable.
    echo.
    pause
    exit /b 1
)

net session >nul 2>&1
if %errorlevel%==0 (
    echo Ejecutando como administrador.
    echo Verificando regla de firewall para TCP 8765...
    netsh advfirewall firewall add rule name="EcoSensor Servidor TCP 8765" dir=in action=allow protocol=TCP localport=8765 profile=private,domain enable=yes >nul 2>&1
    if %errorlevel%==0 (
        echo Firewall OK: puerto TCP 8765 permitido en redes privadas/dominio.
    ) else (
        echo ADVERTENCIA: no se pudo crear/verificar la regla de firewall.
    )
) else (
    echo No se esta ejecutando como administrador.
    echo Si es la primera vez, cierra esta ventana y ejecuta run.bat como administrador.
    echo Despues puedes ejecutarlo normal con doble clic.
)

echo.
echo Iniciando servidor...
echo Abre en esta PC: http://localhost:8765
echo En la red local usa la IP que muestre NiceGUI o mDNS: http://ecosensor-servidor.local:8765
echo.

cd /d "%~dp0app"
"..\python\python.exe" "main.py"

echo.
echo El servidor se cerro.
pause
