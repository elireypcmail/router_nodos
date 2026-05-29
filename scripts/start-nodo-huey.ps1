# Arranca el consumer Huey del nodo (outbox + sync jobs por archivo).
param(
    [string]$NodoDir = ""
)

$ErrorActionPreference = "Stop"
$DeployDir = Join-Path $env:ProgramData "Multishop"
$DirFile = Join-Path $DeployDir "nodo-dir.txt"

if (-not $NodoDir -and (Test-Path $DirFile)) {
    $NodoDir = (Get-Content -LiteralPath $DirFile -Raw).Trim()
}
if (-not $NodoDir) {
    throw "NodoDir no definido"
}

$venvPython = Join-Path $NodoDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "No se encontro $venvPython"
}

Set-Location $NodoDir
& $venvPython -m huey.bin.huey_consumer huey_tasks.huey
