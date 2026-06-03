@echo off
setlocal

cd /d "%~dp0"

echo ========================================
echo Configuracion EcoSensor Servidor Portable
echo ========================================
echo.

net session >nul 2>&1
if not %errorlevel%==0 (
    echo Solicitando permisos de administrador...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs" >nul 2>&1
    exit /b
)

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

echo Verificando regla de firewall para TCP 8765...
netsh advfirewall firewall add rule name="EcoSensor Servidor TCP 8765" dir=in action=allow protocol=TCP localport=8765 profile=private,domain enable=yes >nul 2>&1
if %errorlevel%==0 (
    echo Firewall OK: puerto TCP 8765 permitido en redes privadas/dominio.
) else (
    echo ADVERTENCIA: no se pudo crear/verificar la regla de firewall.
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
echo Ahora puedes ejecutar el servidor sin consola desde el acceso directo del escritorio.
echo Para diagnostico manual, ejecuta run.bat.
echo.
pause
