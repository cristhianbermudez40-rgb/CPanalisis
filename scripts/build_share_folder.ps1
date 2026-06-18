$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distRoot = Join-Path $projectRoot "dist"
$shareRoot = Join-Path $distRoot "CPAnalisis_Compartir"

if (Test-Path $shareRoot) {
    Remove-Item $shareRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $shareRoot | Out-Null

$includeFiles = @(
    "README.md",
    "requirements.txt",
    ".env",
    ".env.example"
)

foreach ($file in $includeFiles) {
    $src = Join-Path $projectRoot $file
    if (Test-Path $src) {
        Copy-Item $src -Destination $shareRoot -Force
    }
}

$includeDirs = @("app", "scripts", "data")
foreach ($dir in $includeDirs) {
    $src = Join-Path $projectRoot $dir
    if (Test-Path $src) {
        Copy-Item $src -Destination (Join-Path $shareRoot $dir) -Recurse -Force
    }
}

# Crear carpeta reportes (donde se guardan los reportes generados)
$reportesDir = Join-Path $shareRoot "reportes"
if (-not (Test-Path $reportesDir)) {
    New-Item -ItemType Directory -Path $reportesDir | Out-Null
}

# Clean cache/noise
Get-ChildItem -Path $shareRoot -Recurse -Directory -Force |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".mypy_cache") } |
    Remove-Item -Recurse -Force

# Startup helper for any workstation
$runBat = @"
@echo off
setlocal
cd /d %~dp0

if not exist reportes\ (
  mkdir reportes
)

if not exist .venv\Scripts\python.exe (
  echo [CPAnalisis] Creando entorno virtual...
  py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
python app\main.py
"@
Set-Content -Path (Join-Path $shareRoot "RUN_CPAnalisis.bat") -Value $runBat -Encoding ASCII

$readmeShare = @"
CPAnalisis - Carpeta Compartible

1) Esta carpeta contiene la app completa para ejecutar en otra maquina.
2) Mantiene la conexion a la misma base de datos usando .env (MYSQL_HOST, MYSQL_USER, etc.).
3) Requisito: que la otra maquina tenga acceso de red/VPN al servidor MySQL y a las impresoras.
4) Ejecutar RUN_CPAnalisis.bat para instalar dependencias y abrir la app.
"@
Set-Content -Path (Join-Path $shareRoot "LEEME_COMPARTIR.txt") -Value $readmeShare -Encoding UTF8
