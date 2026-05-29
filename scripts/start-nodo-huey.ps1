# Starts the nodo Huey consumer (outbox + catalog sync jobs) in the background.
param(
    [string]$NodoDir = ""
)

$ErrorActionPreference = "Stop"
$DeployDir = Join-Path $env:ProgramData "Multishop"
$DirFile = Join-Path $DeployDir "nodo-dir.txt"
$StartLog = Join-Path $DeployDir "nodo-huey-start.log"
$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (Test-Path -LiteralPath $envHelper) {
    . $envHelper
}

function Write-HueyStartLog {
    param([string]$Message)
    if (-not (Test-Path $DeployDir)) {
        New-Item -ItemType Directory -Path $DeployDir -Force | Out-Null
    }
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $StartLog -Value $line -Encoding ASCII -ErrorAction SilentlyContinue
}

function Test-HueyConsumerRunning {
    param([string]$NodoDirPath)
    if (Get-Command Test-MultishopHueyProcessRunning -ErrorAction SilentlyContinue) {
        return (Test-MultishopHueyProcessRunning -NodoDir $NodoDirPath)
    }
    $nodoLower = $NodoDirPath.TrimEnd('\').ToLowerInvariant()
    foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue) {
        $cmd = ($wp.CommandLine -as [string])
        if (-not $cmd) { continue }
        if ($cmd.ToLowerInvariant() -notlike "*$nodoLower*") { continue }
        if ($cmd -match 'huey_consumer') {
            return [int]$wp.ProcessId
        }
    }
    return 0
}

function Start-MultishopHueyConsumer {
    param([string]$NodoDirPath)

    Write-HueyStartLog "=== huey launcher user=$env:USERNAME session=$env:SESSIONNAME ==="

    if (-not $NodoDirPath -and (Test-Path $DirFile)) {
        $NodoDirPath = (Get-Content -LiteralPath $DirFile -Raw).Trim()
    }
    if (-not $NodoDirPath) {
        throw "NodoDir not set (missing nodo-dir.txt in ProgramData\Multishop)"
    }
    if (-not (Test-Path -LiteralPath $NodoDirPath)) {
        throw "NodoDir does not exist: $NodoDirPath"
    }

    $existingPid = Test-HueyConsumerRunning -NodoDirPath $NodoDirPath
    if ($existingPid -gt 0) {
        Write-HueyStartLog "Huey consumer already running PID $existingPid; skip."
        return
    }

    $venvPython = Join-Path $NodoDirPath "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Missing venv python: $venvPython"
    }

    $logOut = Join-Path $DeployDir "nodo-huey.out.log"
    $logErr = Join-Path $DeployDir "nodo-huey.err.log"

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    Write-HueyStartLog "Starting: $venvPython -m huey.bin.huey_consumer huey_tasks.huey (cwd $NodoDirPath)"

    $proc = Start-Process -FilePath $venvPython `
        -ArgumentList @("-m", "huey.bin.huey_consumer", "huey_tasks.huey") `
        -WorkingDirectory $NodoDirPath `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError $logErr `
        -PassThru

    Start-Sleep -Seconds 4

    if ($proc.HasExited) {
        $errTail = ""
        if (Test-Path -LiteralPath $logErr) {
            $errTail = (Get-Content -LiteralPath $logErr -Tail 5 -ErrorAction SilentlyContinue) -join " | "
        }
        throw "Huey exited immediately (code $($proc.ExitCode)). See $logErr. $errTail"
    }

    Write-HueyStartLog "Huey consumer active PID $($proc.Id)"
}

try {
    if (Get-Command Invoke-MultishopStartMutex -ErrorAction SilentlyContinue) {
        Invoke-MultishopStartMutex -Name "Huey" -ScriptBlock { Start-MultishopHueyConsumer -NodoDirPath $NodoDir }
    } else {
        Start-MultishopHueyConsumer -NodoDirPath $NodoDir
    }
} catch {
    Write-HueyStartLog "ERROR: $($_.Exception.Message)"
    throw
}
