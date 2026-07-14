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
$launcherBase = 'start-api'
if (Get-Command Get-MultishopLauncherBasename -ErrorAction SilentlyContinue) {
    $launcherBase = Get-MultishopLauncherBasename
}
$launcherVbs = Join-Path $DeployDir "$launcherBase.vbs"

$nodoDir = Get-MultishopNodoDirFromProgramData
$apiPort = 8443
if ($nodoDir) {
    $apiPort = Get-MultishopNodoApiPort -NodoDir $nodoDir
} else {
    $dirFileLabel = 'router-dir.txt'
    if (Get-Command Get-MultishopDirFileName -ErrorAction SilentlyContinue) {
        $dirFileLabel = Get-MultishopDirFileName
    }
    Write-Warning "No se encontro $dirFileLabel; usando puerto por defecto $apiPort"
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
    $envMap = @{}
    $envPath = Join-Path $nodoDir ".env"
    if (Test-Path -LiteralPath $envPath) {
        $envMap = Read-MultishopEnvFile -Path $envPath
    }
    $hueyWanted = Test-MultishopEnvFlagTrue -Value $envMap['HUEY_ENABLED']
    if ($hueyWanted -and $counts.Huey -lt 1) {
        Write-Host "Huey: HUEY_ENABLED=true pero no hay consumer (Huey=0)." -ForegroundColor Yellow
        if (Get-Command Get-MultishopHueyStartFailureHint -ErrorAction SilentlyContinue) {
            Write-Host "  $(Get-MultishopHueyStartFailureHint -NodoDir $nodoDir)"
        }
        $hueyBase = if (Get-Command Get-MultishopHueyLauncherBasename -ErrorAction SilentlyContinue) {
            Get-MultishopHueyLauncherBasename
        } else { 'start-huey' }
        $hueyVbs = Join-Path $DeployDir "$hueyBase.vbs"
        if (Test-Path -LiteralPath $hueyVbs) {
            Write-Host "  Arrancar ahora: wscript.exe //nologo `"$hueyVbs`"" -ForegroundColor Cyan
        } else {
            Write-Host "  Arrancar ahora: powershell -NoProfile -ExecutionPolicy Bypass -File `"$($PSScriptRoot)\start-nodo-huey.ps1`" -NodoDir `"$nodoDir`"" -ForegroundColor Cyan
        }
    } elseif (-not $hueyWanted) {
        Write-Host "Huey: desactivado (HUEY_ENABLED!=true en .env)." -ForegroundColor DarkGray
    } elseif ($counts.Huey -ge 1) {
        Write-Host "Huey: consumer activo." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Logs:"
$hueyLogs = @(
    (Join-Path $DeployDir "nodo-huey-start.log"),
    (Join-Path $DeployDir "nodo-huey.err.log"),
    (Join-Path $env:LOCALAPPDATA "Multishop\router\nodo-huey-start.log"),
    (Join-Path $env:LOCALAPPDATA "Multishop\router\nodo-huey.err.log")
)
foreach ($p in @($logStart, $logStartLocal, $logOut, $logErr) + $hueyLogs) {
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
