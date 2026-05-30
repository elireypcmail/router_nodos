# Arranca la API del nodo en segundo plano (sin ventana).
# Logs: C:\ProgramData\Multishop\ (preferido) o %LOCALAPPDATA%\Multishop\ si no hay permiso de escritura.
# Puerto de escucha: NODO_PORT en .env (default 8443).

$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (Test-Path -LiteralPath $envHelper) {
    . $envHelper
}
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
        $testFile = Join-Path $Dir "nodo-api-start.log"
        Add-Content -LiteralPath $testFile -Value "" -Encoding ASCII -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Get-MultishopConfigDir {
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
        (Join-Path $env:ProgramData "Multishop"),
        (Join-Path $env:LOCALAPPDATA "Multishop")
    )
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
    $logFile = Join-Path (Get-MultishopLogDir) "nodo-api-start.log"
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
        $logFile = Join-Path $fallback "nodo-api-start.log"
        Add-Content -LiteralPath $logFile -Value $line -Encoding ASCII
    }
}

function Get-MultishopNodoDir {
    param([string]$NodoDirOverride = "")
    if ($NodoDirOverride) {
        return $NodoDirOverride
    }
    $configDir = Get-MultishopConfigDir
    if ($configDir) {
        $dirFile = Join-Path $configDir "nodo-dir.txt"
        if (Test-Path $dirFile) {
            return (Get-Content -LiteralPath $dirFile -Raw).Trim()
        }
    }
    throw "Falta nodo-dir.txt en ProgramData\Multishop. Ejecute el instalador Windows como administrador."
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
        $logOut = Join-Path $MultishopDir "nodo-api.out.log"
        $logErr = Join-Path $MultishopDir "nodo-api.err.log"

        Write-NodoApiLog "=== arranque === user=$env:USERNAME session=$env:SESSIONNAME logdir=$MultishopDir"

        $NodoDir = Get-MultishopNodoDir -NodoDirOverride $NodoDirOverride

        if (-not (Test-Path $NodoDir)) {
            throw "NodoDir no existe: $NodoDir"
        }

        if (-not (Test-Path (Join-Path $NodoDir ".env"))) {
            throw "Falta .env en $NodoDir"
        }

        $apiPort = Get-MultishopNodoApiPort -NodoDir $NodoDir

        if (Get-Command Test-MultishopNodoApiProcessRunning -ErrorAction SilentlyContinue) {
            $existingPid = Test-MultishopNodoApiProcessRunning -NodoDir $NodoDir
            if ($existingPid -gt 0) {
                Write-NodoApiLog "API ya corre (PID $existingPid); no se inicia otra instancia."
                return
            }
        }

        if (Test-NodoApiPortOpen -Port $apiPort) {
            Write-NodoApiLog "API ya escucha en puerto $apiPort; no se inicia otra instancia."
            return
        }

        $python = Join-Path $NodoDir "venv\Scripts\python.exe"
        if (-not (Test-Path $python)) {
            throw "No hay venv en $NodoDir (venv\Scripts\python.exe)"
        }

        Write-NodoApiLog "Iniciando API: $python main.py (cwd $NodoDir)"

        $proc = Start-Process -FilePath $python `
            -ArgumentList "main.py" `
            -WorkingDirectory $NodoDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $logOut `
            -RedirectStandardError $logErr `
            -PassThru

        $deadline = (Get-Date).AddSeconds(45)
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
            throw "python sigue vivo (PID $($proc.Id)) pero puerto $apiPort no escucha tras 45s. Revise $logErr y $logOut"
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
    Start-MultishopNodoApi
}
