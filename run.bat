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

if not exist ".\app\main.py" (
    echo ERROR: No se encontro .\app\main.py
    echo La carpeta app esta incompleta o fue movida.
    echo.
    pause
    exit /b 1
)

echo Iniciando servidor...
echo Abre en esta PC: http://localhost:8765
echo En la red local usa: http://ecosensor.local
echo Si no abre, usa: http://ecosensor.local:8765
echo.

cd /d "%~dp0app"
"..\python\python.exe" "main.py"

echo.
echo El servidor se cerro.
pause
