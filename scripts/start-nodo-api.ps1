# Arranca la API del nodo en segundo plano (sin ventana).
# Logs: C:\ProgramData\Multishop\router\ (fork router) o Multishop\ (nodo padre).
# Puerto de escucha: NODO_PORT en .env (default 8443).

function Get-MultishopApiLogBasenameSafe {
    if (Get-Command Get-MultishopApiLogBasename -ErrorAction SilentlyContinue) {
        return (Get-MultishopApiLogBasename)
    }
    $root = ($PSScriptRoot -as [string])
    if ($root -and $root.ToLowerInvariant() -match '\\multishop\\router$') {
        return 'router-api'
    }
    return 'nodo-api'
}

function Get-MultishopBootstrapLogDir {
    $candidates = @(
        $PSScriptRoot,
        (if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) { Get-MultishopDeployRoot } else { $null }),
        (Join-Path $env:ProgramData 'Multishop\router'),
        (Join-Path $env:ProgramData 'Multishop')
    ) | Where-Object { $_ }
    foreach ($dir in $candidates) {
        try {
            if (-not (Test-Path -LiteralPath $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
            }
            return $dir
        } catch {
            continue
        }
    }
    return $env:TEMP
}

function Write-MultishopBootstrapLog {
    param([string]$Message)
    try {
        $logFile = Join-Path (Get-MultishopBootstrapLogDir) "$(Get-MultishopApiLogBasenameSafe)-start.log"
        $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
        Add-Content -LiteralPath $logFile -Value $line -Encoding ASCII -ErrorAction Stop
    } catch {
        # ultimo recurso: no bloquear arranque por logging
    }
}

$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (Test-Path -LiteralPath $envHelper) {
  try {
    . $envHelper
  } catch {
    Write-MultishopBootstrapLog "WARN: nodo-env.ps1 no cargo: $($_.Exception.Message)"
  }
} else {
  Write-MultishopBootstrapLog "WARN: falta nodo-env.ps1 en $PSScriptRoot (usando fallbacks router/nodo)"
}

Write-MultishopBootstrapLog "start-api.ps1 pid=$PID root=$PSScriptRoot"

if (-not (Get-Command Get-MultishopNodoApiPort -ErrorAction SilentlyContinue)) {
    function Get-MultishopNodoApiPort {
        param([string]$NodoDir, [int]$DefaultPort = 8443)
        return $DefaultPort
    }
}

$script:MultishopLogDir = $null

function Test-MultishopLogDirWritable {
    param([string]$Dir)
    try {
        if (-not (Test-Path $Dir)) {
            New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        }
        $testFile = Join-Path $Dir "$(Get-MultishopApiLogBasenameSafe)-start.log"
        Add-Content -LiteralPath $testFile -Value "" -Encoding ASCII -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Get-MultishopConfigDir {
  if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) {
    $deploy = Get-MultishopDeployRoot
    if (-not (Test-Path -LiteralPath $deploy)) {
      New-Item -ItemType Directory -Path $deploy -Force | Out-Null
    }
    return $deploy
  }
  $programData = Join-Path $env:ProgramData "Multishop"
  if (Test-Path $programData) {
    return $programData
  }
  return $null
}

function Get-MultishopLogDir {
    if ($script:MultishopLogDir) {
        return $script:MultishopLogDir
    }
    $candidates = @(
        $PSScriptRoot,
        (if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) { Get-MultishopDeployRoot } else { $null }),
        (Join-Path $env:ProgramData "Multishop\router"),
        (Join-Path $env:ProgramData "Multishop"),
        (Join-Path $env:LOCALAPPDATA "Multishop")
    ) | Where-Object { $_ }
    foreach ($dir in $candidates) {
        if (Test-MultishopLogDirWritable -Dir $dir) {
            $script:MultishopLogDir = $dir
            return $dir
        }
    }
    throw "No se puede escribir logs en ProgramData ni LocalAppData\Multishop"
}

function Write-NodoApiLog {
    param([string]$Message)
    $logFile = Join-Path (Get-MultishopLogDir) "$(Get-MultishopApiLogBasenameSafe)-start.log"
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try {
        Add-Content -LiteralPath $logFile -Value $line -Encoding ASCII -ErrorAction Stop
    } catch {
        $script:MultishopLogDir = $null
        $fallback = Join-Path $env:LOCALAPPDATA "Multishop"
        if (-not (Test-Path $fallback)) {
            New-Item -ItemType Directory -Path $fallback -Force | Out-Null
        }
        $script:MultishopLogDir = $fallback
        $logFile = Join-Path $fallback "$(Get-MultishopApiLogBasenameSafe)-start.log"
        Add-Content -LiteralPath $logFile -Value $line -Encoding ASCII
    }
}

function Get-MultishopNodoDir {
    param([string]$NodoDirOverride = "")
    if ($NodoDirOverride) {
        return $NodoDirOverride
    }
    foreach ($name in @('router-dir.txt', 'nodo-dir.txt')) {
        $localDirFile = Join-Path $PSScriptRoot $name
        if (Test-Path -LiteralPath $localDirFile) {
            $dir = (Get-Content -LiteralPath $localDirFile -Raw).Trim()
            if ($dir) { return $dir }
        }
    }
    $configDir = Get-MultishopConfigDir
    if ($configDir) {
        $dirFile = if (Get-Command Get-MultishopDirFilePath -ErrorAction SilentlyContinue) {
            Get-MultishopDirFilePath
        } else {
            Join-Path $configDir "nodo-dir.txt"
        }
        if (Test-Path $dirFile) {
            return (Get-Content -LiteralPath $dirFile -Raw).Trim()
        }
    }
    throw "Falta $(if (Get-Command Get-MultishopDirFileName -ErrorAction SilentlyContinue) { Get-MultishopDirFileName } else { 'nodo-dir.txt' }) en ProgramData\Multishop. Ejecute el instalador Windows como administrador."
}

function Test-NodoApiPortOpen {
    param([int]$Port = 8443)
    if (Get-Command Test-MultishopNodoApiTcpPortListening -ErrorAction SilentlyContinue) {
        return (Test-MultishopNodoApiTcpPortListening -Port $Port)
    }
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return ($null -ne $conn)
    } catch {
        $netstat = netstat -ano 2>$null | Select-String ":$Port\s"
        return ($null -ne $netstat)
    }
}

function Start-MultishopNodoApi {
    param(
        [string]$NodoDirOverride = ""
    )

    $startBody = {
        param($NodoDirOverride)

        $MultishopDir = Get-MultishopLogDir
        $logBasename = Get-MultishopApiLogBasenameSafe
        $logOut = Join-Path $MultishopDir "$logBasename.out.log"
        $logErr = Join-Path $MultishopDir "$logBasename.err.log"

        Write-NodoApiLog "=== arranque === user=$env:USERNAME session=$env:SESSIONNAME logdir=$MultishopDir"

        $NodoDir = Get-MultishopNodoDir -NodoDirOverride $NodoDirOverride

        if (-not (Test-Path $NodoDir)) {
            throw "NodoDir no existe: $NodoDir"
        }

        if (-not (Test-Path (Join-Path $NodoDir ".env"))) {
            throw "Falta .env en $NodoDir"
        }

        $apiPort = Get-MultishopNodoApiPort -NodoDir $NodoDir

        if (Test-NodoApiPortOpen -Port $apiPort) {
            Write-NodoApiLog "API ya escucha en puerto $apiPort; no se inicia otra instancia."
            return
        }

        if (Get-Command Stop-MultishopNodoApiLeaderProcess -ErrorAction SilentlyContinue) {
            if (Stop-MultishopNodoApiLeaderProcess -NodoDir $NodoDir -Reason "puerto $apiPort no escucha") {
                Write-NodoApiLog "Proceso main.py previo sin puerto $apiPort; detenido antes de reiniciar."
            }
        } elseif (Get-Command Test-MultishopNodoApiProcessRunning -ErrorAction SilentlyContinue) {
            $existingPid = Test-MultishopNodoApiProcessRunning -NodoDir $NodoDir
            if ($existingPid -gt 0) {
                Write-NodoApiLog "Proceso main.py PID $existingPid sin puerto $apiPort; deteniendo ..."
                Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }
        }

        $python = Join-Path $NodoDir "venv\Scripts\python.exe"
        if (-not (Test-Path $python)) {
            throw "No hay venv en $NodoDir (venv\Scripts\python.exe)"
        }

        if (Get-Command Wait-MultishopNodoMysqlReady -ErrorAction SilentlyContinue) {
            Wait-MultishopNodoMysqlReady -NodoDir $NodoDir -LogFn {
                param($Message)
                Write-NodoApiLog $Message
            }
        }

        $startupWaitSec = 45
        if (Get-Command Get-MultishopNodoApiStartupWaitSeconds -ErrorAction SilentlyContinue) {
            $startupWaitSec = Get-MultishopNodoApiStartupWaitSeconds -NodoDir $NodoDir
        }

        Write-NodoApiLog "Iniciando API: $python main.py (cwd $NodoDir, espera puerto ${startupWaitSec}s)"

        $proc = Start-Process -FilePath $python `
            -ArgumentList "main.py" `
            -WorkingDirectory $NodoDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $logOut `
            -RedirectStandardError $logErr `
            -PassThru

        $deadline = (Get-Date).AddSeconds($startupWaitSec)
        $listening = $false
        while ((Get-Date) -lt $deadline) {
            if ($proc.HasExited) {
                break
            }
            if (Test-NodoApiPortOpen -Port $apiPort) {
                $listening = $true
                break
            }
            Start-Sleep -Seconds 2
        }

        if ($proc.HasExited) {
            $errTail = ""
            if (Test-Path $logErr) {
                $errTail = (Get-Content $logErr -Tail 20 -ErrorAction SilentlyContinue) -join " | "
            }
            throw "python salio con codigo $($proc.ExitCode). Revise $logErr. $errTail"
        }

        if (-not $listening) {
            if (-not $proc.HasExited) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                Write-NodoApiLog "Proceso PID $($proc.Id) detenido: no escuchaba en puerto $apiPort tras ${startupWaitSec}s."
            }
            throw "python no escucho en puerto $apiPort tras ${startupWaitSec}s. Revise $logErr y $logOut"
        }

        Write-NodoApiLog "API activa PID $($proc.Id) puerto $apiPort"
    }

    try {
        if (Get-Command Invoke-MultishopStartMutex -ErrorAction SilentlyContinue) {
            Invoke-MultishopStartMutex -Name "Api" -ScriptBlock { & $startBody $NodoDirOverride }
        } else {
            & $startBody $NodoDirOverride
        }
    } catch {
        Write-NodoApiLog "ERROR: $($_.Exception.Message)"
        throw
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference = "Stop"
    try {
        Start-MultishopNodoApi
    } catch {
        Write-MultishopBootstrapLog "ERROR: $($_.Exception.Message)"
        throw
    }
}
