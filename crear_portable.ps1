param(
    [string]$PortableDir = "C:\Users\kyo_a\Documents\EduardoRamos\Python\EcoSensorServidorPortable",
    [string]$SourceDir = "C:\Users\kyo_a\Documents\EduardoRamos\Python\Ecosensor-Servidor-Distribucion",
    [string]$PythonZip = "C:\Users\kyo_a\Downloads\python-3.12.10-embed-amd64.zip"
)

$ErrorActionPreference = "Stop"

function Write-Step($text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}

Write-Step "Validando rutas"
if (!(Test-Path $SourceDir)) {
    throw "No existe SourceDir: $SourceDir"
}
if (!(Test-Path $PythonZip)) {
    throw "No existe PythonZip: $PythonZip"
}

Write-Step "Creando estructura portable"
New-Item -ItemType Directory -Force -Path $PortableDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PortableDir "python") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PortableDir "app") | Out-Null

Write-Step "Limpiando carpetas anteriores app/python"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $PortableDir "app\*")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $PortableDir "python\*")

Write-Step "Extrayendo Python portable"
Expand-Archive -Path $PythonZip -DestinationPath (Join-Path $PortableDir "python") -Force

Write-Step "Habilitando import site en Python embeddable"
$pthFile = Get-ChildItem -Path (Join-Path $PortableDir "python") -Filter "python*._pth" | Select-Object -First 1
if (!$pthFile) {
    throw "No se encontro archivo python*._pth dentro de la carpeta python portable."
}
$pthContent = Get-Content $pthFile.FullName
$pthContent = $pthContent | ForEach-Object {
    if ($_ -eq "#import site") { "import site" } else { $_ }
}
Set-Content -Path $pthFile.FullName -Value $pthContent -Encoding ASCII

Write-Step "Copiando app limpia"
$AppDir = Join-Path $PortableDir "app"
$excludeDirs = @(
    ".git", ".venv", "venv", "env", "__pycache__", "build", "dist", "data", "output", "installer"
)
$excludeFiles = @(
    "*.pyc", "*.pyo", "*.spec", "*.log", "*.tmp", "*.bak", "*.exe"
)

$robocopyArgs = @(
    $SourceDir,
    $AppDir,
    "/E",
    "/XD"
) + $excludeDirs + @(
    "/XF"
) + $excludeFiles + @(
    "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
)

& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "Robocopy fallo con codigo $LASTEXITCODE"
}

Write-Step "Copiando run.bat y README_PORTABLE.txt a la raiz portable"
Copy-Item -Force (Join-Path $SourceDir "run.bat") (Join-Path $PortableDir "run.bat")
Copy-Item -Force (Join-Path $SourceDir "README_PORTABLE.txt") (Join-Path $PortableDir "README.txt")

Write-Step "Instalando pip en Python portable si hace falta"
$PythonExe = Join-Path $PortableDir "python\python.exe"
$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$PipCheck = & $PythonExe -m pip --version 2>$null
$PipExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($PipExitCode -ne 0) {
    Write-Host "pip no esta instalado en el Python portable; descargando get-pip.py..."
    $GetPip = Join-Path $PortableDir "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
    & $PythonExe $GetPip
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo instalar pip en Python portable."
    }
    Remove-Item -Force $GetPip -ErrorAction SilentlyContinue
} else {
    Write-Host "pip ya esta disponible: $PipCheck"
}

Write-Step "Instalando dependencias de la app"
& $PythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Fallo actualizando pip." }

& $PythonExe -m pip install -r (Join-Path $AppDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Fallo instalando requirements.txt." }

Write-Step "Validando imports principales"
& $PythonExe -c "import nicegui, fastapi, zeroconf; print('Dependencias OK')"
if ($LASTEXITCODE -ne 0) { throw "Fallo validando dependencias principales." }

Write-Step "Validando sintaxis de la app"
& $PythonExe -m py_compile (Join-Path $AppDir "main.py")
if ($LASTEXITCODE -ne 0) { throw "Fallo py_compile main.py." }

Write-Host ""
Write-Host "Portable creado correctamente en:" -ForegroundColor Green
Write-Host "  $PortableDir" -ForegroundColor Green
Write-Host ""
Write-Host "Primera ejecucion recomendada:" -ForegroundColor Yellow
Write-Host "  Clic derecho en run.bat > Ejecutar como administrador"
Write-Host ""
