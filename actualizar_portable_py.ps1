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

Write-Step "Deteniendo actualizacion si el servidor portable esta abierto"
Write-Host "Si el servidor portable esta ejecutandose, cierralo antes de continuar." -ForegroundColor Yellow

Write-Step "Eliminando archivos .py anteriores en la app portable"
Get-ChildItem -Path $AppDir -Recurse -File -Filter "*.py" |
    Where-Object { !(Test-IsExcludedPath $_.FullName $AppDir) } |
    Remove-Item -Force

Write-Step "Copiando archivos .py actualizados"
$sourceFiles = Get-ChildItem -Path $SourceDir -Recurse -File -Filter "*.py" |
    Where-Object { !(Test-IsExcludedPath $_.FullName $SourceDir) }

foreach ($file in $sourceFiles) {
    $relative = Get-RelativePathCompat $SourceDir $file.FullName
    $dest = Join-Path $AppDir $relative
    $destDir = Split-Path -Parent $dest
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    Copy-Item -Force $file.FullName $dest
}

Write-Step "Validando sintaxis con Python portable si esta disponible"
$PythonExe = Join-Path $PortableDir "python\python.exe"
if (Test-Path $PythonExe) {
    & $PythonExe -m compileall -q $AppDir
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la validacion de sintaxis de los .py copiados."
    }
    Write-Host "Sintaxis OK" -ForegroundColor Green
} else {
    Write-Host "No se encontro Python portable en $PythonExe; se omitio validacion de sintaxis." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Archivos .py actualizados correctamente en:" -ForegroundColor Green
Write-Host "  $AppDir" -ForegroundColor Green
Write-Host ""
Write-Host "Puedes iniciar de nuevo el portable con run.bat" -ForegroundColor Yellow
