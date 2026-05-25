# Estado de la API nodo en background.
$DeployDir = Join-Path $env:ProgramData "Multishop"
$logStart = Join-Path $DeployDir "nodo-api-start.log"
$logStartLocal = Join-Path $env:LOCALAPPDATA "Multishop\nodo-api-start.log"
$logOut = Join-Path $DeployDir "nodo-api.out.log"
$logErr = Join-Path $DeployDir "nodo-api.err.log"

Write-Host "=== Multishop nodo API ==="
Write-Host ""

$portOpen = $false
try {
    $conn = Get-NetTCPConnection -LocalPort 8443 -State Listen -ErrorAction SilentlyContinue
    $portOpen = ($null -ne $conn)
} catch {
    $portOpen = [bool](netstat -ano 2>$null | Select-String ":8443\s")
}

if ($portOpen) {
    Write-Host "Puerto 8443: ESCUCHANDO" -ForegroundColor Green
} else {
    Write-Host "Puerto 8443: no activo" -ForegroundColor Yellow
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
Write-Host '  curl http://127.0.0.1:8443/api/health -H "Authorization: Bearer <TOKEN>"'
Write-Host ""
Write-Host "Arrancar:"
Write-Host "  wscript.exe //nologo $DeployDir\start-nodo-api.vbs"
