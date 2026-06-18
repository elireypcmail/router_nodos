# Estado de la API nodo router (puerto segun NODO_PORT en .env).

$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (Test-Path -LiteralPath $envHelper) {
    . $envHelper
}

$DeployDir = if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) {
    Get-MultishopDeployRoot
} else {
    Join-Path $env:ProgramData "Multishop\router"
}
$logBasename = if (Get-Command Get-MultishopApiLogBasename -ErrorAction SilentlyContinue) {
    Get-MultishopApiLogBasename
} else {
    'router-api'
}
$logStart = Join-Path $DeployDir "$logBasename-start.log"
$logStartLocal = Join-Path $env:LOCALAPPDATA "Multishop\$logBasename-start.log"
$logOut = Join-Path $DeployDir "$logBasename.out.log"
$logErr = Join-Path $DeployDir "$logBasename.err.log"
$launcherVbs = Join-Path $DeployDir "$(if (Get-Command Get-MultishopLauncherBasename -ErrorAction SilentlyContinue) { Get-MultishopLauncherBasename } else { 'start-api' }).vbs"

$nodoDir = Get-MultishopNodoDirFromProgramData
$apiPort = 8443
if ($nodoDir) {
    $apiPort = Get-MultishopNodoApiPort -NodoDir $nodoDir
} else {
    Write-Warning "No se encontro $(if (Get-Command Get-MultishopDirFileName -ErrorAction SilentlyContinue) { Get-MultishopDirFileName } else { 'router-dir.txt' }); usando puerto por defecto $apiPort"
}

Write-Host "=== Multishop router nodo API ==="
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

$apiLeaderPid = 0
if ($nodoDir -and (Get-Command Test-MultishopNodoApiProcessRunning -ErrorAction SilentlyContinue)) {
    $apiLeaderPid = Test-MultishopNodoApiProcessRunning -NodoDir $nodoDir
}

if ($portOpen) {
    Write-Host "Puerto $apiPort (NODO_PORT): ESCUCHANDO" -ForegroundColor Green
} else {
    Write-Host "Puerto $apiPort (NODO_PORT): no activo" -ForegroundColor Yellow
    if ($apiLeaderPid -gt 0) {
        Write-Host "  AVISO: hay main.py (PID $apiLeaderPid) pero el puerto no escucha (proceso colgado)." -ForegroundColor Red
        Write-Host "  Accion: wscript.exe //nologo $launcherVbs (reinicia tras matar el zombie)"
    }
}

if ($apiLeaderPid -gt 0) {
    Write-Host "Proceso API (main.py): PID $apiLeaderPid" -ForegroundColor Green
} else {
    Write-Host "Proceso API (main.py): no detectado" -ForegroundColor Yellow
}

if ($nodoDir -and (Get-Command Get-MultishopNodoProcessCounts -ErrorAction SilentlyContinue)) {
    $counts = Get-MultishopNodoProcessCounts -NodoDir $nodoDir
    Write-Host "Procesos en $($nodoDir): API=$($counts.Api) Huey=$($counts.Huey)"
}

Write-Host ""
Write-Host "Logs:"
foreach ($p in @($logStart, $logStartLocal, $logOut, $logErr)) {
    if (Test-Path -LiteralPath $p) {
        Write-Host "  $p"
    }
}

if (Get-Command Get-MultishopScheduledTaskNames -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host "Tareas ONSTART:"
    foreach ($tn in (Get-MultishopScheduledTaskNames)) {
        $exists = $false
        foreach ($q in @($tn, "\$tn")) {
            schtasks.exe /Query /TN $q 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $exists = $true; break }
        }
        if ($exists) {
            Write-Host "  [OK] $tn" -ForegroundColor Green
        } else {
            Write-Host "  [--] $tn"
        }
    }
}
