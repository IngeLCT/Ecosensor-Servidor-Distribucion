@echo off
setlocal

cd /d "%~dp0"

net session >nul 2>&1
if not %errorlevel%==0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs" >nul 2>&1
    exit /b
)

echo ========================================
echo Configuracion EcoSensor Servidor
echo ========================================
echo.

echo Ejecutando como administrador.
echo.

if not exist ".\run.bat" (
    echo ERROR: No se encontro .\run.bat
    echo Verifica que config.bat este dentro de la carpeta EcoSensorServidorPortable.
    echo.
    pause
    exit /b 1
)

if not exist ".\run_hidden.vbs" (
    echo ERROR: No se encontro .\run_hidden.vbs
    echo Actualiza el portable con actualizar_portable_py.ps1 o vuelve a crear el portable.
    echo.
    pause
    exit /b 1
)

echo Configurando reglas de firewall...

REM Elimina reglas anteriores para evitar duplicados si config.bat se ejecuta varias veces.
netsh advfirewall firewall delete rule name="EcoSensor Servidor TCP 8765" >nul 2>&1
netsh advfirewall firewall delete rule name="EcoSensor Servidor mDNS UDP 5353" >nul 2>&1

set "FW_ERROR=0"

REM Puerto HTTP de NiceGUI/Uvicorn para abrir http://IP-DEL-SERVIDOR:8765/
netsh advfirewall firewall add rule name="EcoSensor Servidor TCP 8765" dir=in action=allow protocol=TCP localport=8765 profile=any remoteip=localsubnet enable=yes >nul 2>&1
if errorlevel 1 set "FW_ERROR=1"

REM Puerto mDNS para resolver ecosensor-servidor.local en la red local.
netsh advfirewall firewall add rule name="EcoSensor Servidor mDNS UDP 5353" dir=in action=allow protocol=UDP localport=5353 profile=any remoteip=localsubnet enable=yes >nul 2>&1
if errorlevel 1 set "FW_ERROR=1"

if "%FW_ERROR%"=="0" (
    echo Firewall OK: TCP 8765 y UDP 5353 habilitados para dominio, privado y publico.
) else (
    echo ADVERTENCIA: no se pudieron crear una o mas reglas de firewall.
    echo Ejecuta este archivo como administrador y revisa Seguridad de Windows ^> Firewall.
)

echo Configurando acceso sin puerto: http://ecosensor.local ...

REM Portproxy requiere el servicio IP Helper.
sc query iphlpsvc | find "RUNNING" >nul 2>&1
if errorlevel 1 (
    net start iphlpsvc >nul 2>&1
)

REM Elimina redireccion anterior si existia.
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=80 >nul 2>&1

REM Redirige el puerto HTTP normal 80 hacia NiceGUI en 8765.
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=80 connectaddress=127.0.0.1 connectport=8765 >nul 2>&1

REM Abre el puerto 80 solo para la red local.
netsh advfirewall firewall delete rule name="EcoSensor Acceso HTTP TCP 80" >nul 2>&1
netsh advfirewall firewall add rule name="EcoSensor Acceso HTTP TCP 80" dir=in action=allow protocol=TCP localport=80 profile=any remoteip=localsubnet enable=yes >nul 2>&1

if errorlevel 1 (
    echo ADVERTENCIA: no se pudo configurar el acceso sin puerto.
    echo Puedes seguir usando http://ecosensor.local:8765
) else (
    echo Acceso sin puerto OK: http://ecosensor.local
)

echo.
echo Creando/verificando acceso directo en el escritorio...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$desktop=[Environment]::GetFolderPath('DesktopDirectory'); $shortcut=Join-Path $desktop 'EcoSensor Servidor.lnk'; $workdir='%~dp0'; $target=Join-Path $env:SystemRoot 'System32\wscript.exe'; $script=Join-Path $workdir 'run_hidden.vbs'; $icon=Join-Path $workdir 'app\EcoSensor_WiFi.ico'; $shell=New-Object -ComObject WScript.Shell; $link=$shell.CreateShortcut($shortcut); $link.TargetPath=$target; $link.Arguments=([char]34)+$script+([char]34); $link.WorkingDirectory=$workdir; $link.Description='EcoSensor Servidor Portable'; $link.WindowStyle=7; if (Test-Path $icon) { $link.IconLocation=$icon }; $link.Save()" >nul 2>&1
if %errorlevel%==0 (
    echo Acceso directo OK: EcoSensor Servidor.lnk
) else (
    echo ADVERTENCIA: no se pudo crear/verificar el acceso directo del escritorio.
)

echo.
echo Configuracion terminada.
echo Ahora puedes ejecutar el servidor desde el acceso directo del escritorio.
echo.
pause
