param(
    [string]$PortableDir = "C:\Users\kyo_a\Documents\EduardoRamos\Python\EcoSensorServidorPortable",
    [string]$SourceDir = "C:\Users\kyo_a\Documents\EduardoRamos\Python\Ecosensor-Servidor-Distribucion"
)

$ErrorActionPreference = "Stop"

function Write-Step($text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}

function Get-RelativePathCompat($Root, $Path) {
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $pathFull = [System.IO.Path]::GetFullPath($Path)

    if (!$rootFull.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $rootFull = $rootFull + [System.IO.Path]::DirectorySeparatorChar
    }

    $rootUri = New-Object System.Uri($rootFull)
    $pathUri = New-Object System.Uri($pathFull)
    $relativeUri = $rootUri.MakeRelativeUri($pathUri)
    $relative = [System.Uri]::UnescapeDataString($relativeUri.ToString())
    return $relative -replace '/', [System.IO.Path]::DirectorySeparatorChar
}

function Test-IsExcludedPath($Path, $Root) {
    $relative = Get-RelativePathCompat $Root $Path
    $parts = $relative -split '[\\/]+'
    $excludedDirs = @('.git', '.venv', 'venv', 'env', '__pycache__', 'build', 'dist', 'data', 'output', 'installer')
    foreach ($part in $parts) {
        if ($excludedDirs -contains $part) {
            return $true
        }
    }
    return $false
}

Write-Step "Validando rutas"
if (!(Test-Path $SourceDir)) {
    throw "No existe SourceDir: $SourceDir"
}

$AppDir = Join-Path $PortableDir "app"
if (!(Test-Path $AppDir)) {
    throw "No existe la app portable: $AppDir. Primero crea el portable con crear_portable.ps1"
}

Write-Step "Aviso"
Write-Host "Si el servidor portable esta ejecutandose, cierralo antes de continuar." -ForegroundColor Yellow

Write-Step "Copiando archivos .py actualizados"
$sourceFiles = Get-ChildItem -Path $SourceDir -Recurse -Filter "*.py" |
    Where-Object { !$_.PSIsContainer -and !(Test-IsExcludedPath $_.FullName $SourceDir) }

if (!$sourceFiles -or $sourceFiles.Count -eq 0) {
    throw "No se encontraron archivos .py en SourceDir: $SourceDir"
}

$copied = 0
foreach ($file in $sourceFiles) {
    $relative = Get-RelativePathCompat $SourceDir $file.FullName
    $dest = Join-Path $AppDir $relative
    $destDir = Split-Path -Parent $dest
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    Copy-Item -Force $file.FullName $dest
    $copied += 1
}
Write-Host "Archivos .py copiados: $copied" -ForegroundColor Green

Write-Step "Copiando config.bat, run.bat y run_hidden.vbs actualizados"
Copy-Item -Force (Join-Path $SourceDir "config.bat") (Join-Path $PortableDir "config.bat")
Copy-Item -Force (Join-Path $SourceDir "run.bat") (Join-Path $PortableDir "run.bat")
Copy-Item -Force (Join-Path $SourceDir "run_hidden.vbs") (Join-Path $PortableDir "run_hidden.vbs")

Write-Step "Conservando README.txt del portable"
Write-Host "README.txt no se sobrescribe para respetar cambios manuales." -ForegroundColor Yellow

Write-Step "Asegurando ruta de app en Python embeddable"
$pthFile = Get-ChildItem -Path (Join-Path $PortableDir "python") -Filter "python*._pth" | Select-Object -First 1
if (!$pthFile) {
    throw "No se encontro archivo python*._pth dentro de la carpeta python portable."
}
$pthContent = Get-Content $pthFile.FullName
if (!($pthContent -contains "..\app")) {
    $updatedPth = @()
    $inserted = $false
    foreach ($line in $pthContent) {
        if (!$inserted -and ($line -eq "import site" -or $line -eq "#import site")) {
            $updatedPth += "..\app"
            $inserted = $true
        }
        if ($line -eq "#import site") {
            $updatedPth += "import site"
        } else {
            $updatedPth += $line
        }
    }
    if (!$inserted) {
        $updatedPth += "..\app"
    }
    Set-Content -Path $pthFile.FullName -Value $updatedPth -Encoding ASCII
}

Write-Step "Validando estructura minima"
$requiredPaths = @(
    "main.py",
    "config.py",
    "services\__init__.py",
    "services\windows_asyncio.py",
    "pages\__init__.py",
    "shared\__init__.py",
    "storage\__init__.py"
)
foreach ($required in $requiredPaths) {
    $full = Join-Path $AppDir $required
    if (!(Test-Path $full)) {
        throw "Falta archivo requerido en portable: $full"
    }
}

Write-Step "Validando import principal con Python portable"
$PythonExe = Join-Path $PortableDir "python\python.exe"
if (Test-Path $PythonExe) {
    Push-Location $AppDir
    try {
        & $PythonExe -c "import services.windows_asyncio; import config; print('Imports OK')"
        if ($LASTEXITCODE -ne 0) {
            throw "Fallo la validacion de imports principales."
        }
        & $PythonExe -m compileall -q $AppDir
        if ($LASTEXITCODE -ne 0) {
            throw "Fallo la validacion de sintaxis de los .py copiados."
        }
    } finally {
        Pop-Location
    }
    Write-Host "Sintaxis OK" -ForegroundColor Green
} else {
    Write-Host "No se encontro Python portable en $PythonExe; se omitio validacion de sintaxis." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Archivos .py actualizados correctamente en:" -ForegroundColor Green
Write-Host "  $AppDir" -ForegroundColor Green
Write-Host ""
Write-Host "Ejecuta config.bat para actualizar firewall y acceso directo sin consola." -ForegroundColor Yellow
Write-Host "Despues inicia el portable desde el acceso directo. Para diagnostico manual usa run.bat." -ForegroundColor Yellow
