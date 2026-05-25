# Estado de la API nodo en background (puerto segun NODO_PORT en .env).

$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (Test-Path -LiteralPath $envHelper) {
    . $envHelper
}

$DeployDir = Join-Path $env:ProgramData "Multishop"
$logStart = Join-Path $DeployDir "nodo-api-start.log"
$logStartLocal = Join-Path $env:LOCALAPPDATA "Multishop\nodo-api-start.log"
$logOut = Join-Path $DeployDir "nodo-api.out.log"
$logErr = Join-Path $DeployDir "nodo-api.err.log"

$nodoDir = Get-MultishopNodoDirFromProgramData
$apiPort = 8443
if ($nodoDir) {
    $apiPort = Get-MultishopNodoApiPort -NodoDir $nodoDir
} else {
    Write-Warning "No se encontro nodo-dir.txt; usando puerto por defecto $apiPort"
}

Write-Host "=== Multishop nodo API ==="
if ($nodoDir) {
    Write-Host "Nodo: $nodoDir"
}
Write-Host ""

$portOpen = $false
try {
    $conn = Get-NetTCPConnection -LocalPort $apiPort -State Listen -ErrorAction SilentlyContinue
    $portOpen = ($null -ne $conn)
} catch {
    $portOpen = [bool](netstat -ano 2>$null | Select-String ":$apiPort\s")
}

if ($portOpen) {
    Write-Host "Puerto $apiPort (NODO_PORT): ESCUCHANDO" -ForegroundColor Green
} else {
    Write-Host "Puerto $apiPort (NODO_PORT): no activo" -ForegroundColor Yellow
}

$procs = Get-Process python, pythonw -ErrorAction SilentlyContinue
if ($procs) {
    Write-Host ""
    Write-Host "Procesos Python:"
    $procs | Format-Table Id, ProcessName, Path -AutoSize
} else {
    Write-Host ""
    Write-Host "No hay procesos python/pythonw."
}

Write-Host "Logs:"
Write-Host "  $logStart"
Write-Host "  $logStartLocal"
Write-Host "  $logOut"
Write-Host "  $logErr"
if (Test-Path $logStart) {
    Write-Host "--- nodo-api-start.log (ProgramData) ---"
    Get-Content $logStart -Tail 10 -ErrorAction SilentlyContinue
} elseif (Test-Path $logStartLocal) {
    Write-Host "--- nodo-api-start.log (LocalAppData) ---"
    Get-Content $logStartLocal -Tail 10 -ErrorAction SilentlyContinue
}
if (Test-Path $logOut) {
    Write-Host "--- nodo-api.out.log ---"
    Get-Content $logOut -Tail 10 -ErrorAction SilentlyContinue
}
if (Test-Path $logErr) {
    Write-Host "--- nodo-api.err.log ---"
    Get-Content $logErr -Tail 15 -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Health:"
Write-Host "  curl http://127.0.0.1:$apiPort/api/health -H `"Authorization: Bearer <TOKEN>`""
Write-Host ""
Write-Host "Arrancar:"
Write-Host "  wscript.exe //nologo $DeployDir\start-nodo-api.vbs"
