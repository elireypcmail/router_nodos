# Starts the nodo Huey consumer (outbox + catalog sync jobs) in the background.
param(
    [string]$NodoDir = "",
    [switch]$SkipMutex
)

$ErrorActionPreference = "Stop"

$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (Test-Path -LiteralPath $envHelper) {
    . $envHelper
}

function Get-MultishopHueyDeployRoot {
    if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) {
        return (Get-MultishopDeployRoot)
    }
    # Copiado a ProgramData sin nodo-env: inferir producto por carpeta del launcher.
    $root = ($PSScriptRoot -as [string])
    if ($root -and $root.ToLowerInvariant() -match '\\multishop\\router$') {
        return (Join-Path $env:ProgramData 'Multishop\router')
    }
    if ($root -and $root.ToLowerInvariant() -match '\\multishop\\nodo$') {
        return (Join-Path $env:ProgramData 'Multishop\nodo')
    }
    foreach ($candidate in @(
            (Join-Path $env:ProgramData 'Multishop\router'),
            (Join-Path $env:ProgramData 'Multishop\nodo'),
            (Join-Path $env:ProgramData 'Multishop')
        )) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return (Join-Path $env:ProgramData 'Multishop')
}

function Get-MultishopHueyNodoDir {
    param([string]$NodoDirOverride = "")
    if ($NodoDirOverride) {
        return $NodoDirOverride.Trim().TrimEnd('\')
    }
    foreach ($name in @('router-dir.txt', 'nodo-dir.txt')) {
        $local = Join-Path $PSScriptRoot $name
        if (Test-Path -LiteralPath $local) {
            $dir = (Get-Content -LiteralPath $local -Raw).Trim()
            if ($dir) { return $dir.TrimEnd('\') }
        }
    }
    if (Get-Command Get-MultishopDirFilePath -ErrorAction SilentlyContinue) {
        $dirFile = Get-MultishopDirFilePath
        if (Test-Path -LiteralPath $dirFile) {
            $dir = (Get-Content -LiteralPath $dirFile -Raw).Trim()
            if ($dir) { return $dir.TrimEnd('\') }
        }
    }
    $deploy = Get-MultishopHueyDeployRoot
    foreach ($name in @('router-dir.txt', 'nodo-dir.txt')) {
        $path = Join-Path $deploy $name
        if (Test-Path -LiteralPath $path) {
            $dir = (Get-Content -LiteralPath $path -Raw).Trim()
            if ($dir) { return $dir.TrimEnd('\') }
        }
    }
    # Fallback: Program Files\Multishop\router|nodo
    foreach ($leaf in @('router', 'nodo')) {
        $pf = Join-Path ${env:ProgramFiles} (Join-Path 'Multishop' $leaf)
        if (Test-Path -LiteralPath (Join-Path $pf 'main.py')) {
            return $pf
        }
    }
    throw "NodoDir not set (falta router-dir.txt / nodo-dir.txt en $deploy). Reejecute nodo-api-windows-install.ps1 como administrador."
}

$DeployDir = Get-MultishopHueyDeployRoot
if (-not (Test-Path -LiteralPath $DeployDir)) {
    New-Item -ItemType Directory -Path $DeployDir -Force | Out-Null
}
$StartLog = Join-Path $DeployDir "nodo-huey-start.log"

function Write-HueyStartLog {
    param([string]$Message)
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

    Write-HueyStartLog "=== huey launcher user=$env:USERNAME session=$env:SESSIONNAME deploy=$DeployDir ==="

    $NodoDirPath = Get-MultishopHueyNodoDir -NodoDirOverride $NodoDirPath
    Write-HueyStartLog "NodoDir=$NodoDirPath"

    if (-not (Test-Path -LiteralPath $NodoDirPath)) {
        throw "NodoDir does not exist: $NodoDirPath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $NodoDirPath 'main.py'))) {
        throw "NodoDir does not look like a node install (missing main.py): $NodoDirPath"
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

    if (Get-Command Ensure-NodoWritableDataDir -ErrorAction SilentlyContinue) {
        Ensure-NodoWritableDataDir -NodoDir $NodoDirPath
    } else {
        $dataDir = Join-Path $NodoDirPath "data"
        if (-not (Test-Path -LiteralPath $dataDir)) {
            New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
        }
    }

    $logErr = Join-Path $DeployDir "nodo-huey.err.log"

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    Write-HueyStartLog "Starting: $venvPython -m huey.bin.huey_consumer huey_tasks.huey (cwd $NodoDirPath)"

    # Sin redirección de stdout/stderr: huey_consumer es long-running y puede bloquear
    # el pipe si el padre no lee (instalador con -Wait quedaría colgado).
    $proc = Start-Process -FilePath $venvPython `
        -ArgumentList @("-m", "huey.bin.huey_consumer", "-w", "1", "huey_tasks.huey") `
        -WorkingDirectory $NodoDirPath `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 3

    if ($proc.HasExited) {
        $errTail = ""
        if (Test-Path -LiteralPath $logErr) {
            $errTail = (Get-Content -LiteralPath $logErr -Tail 8 -ErrorAction SilentlyContinue) -join " | "
        }
        throw "Huey exited immediately (code $($proc.ExitCode)). Revise $logErr. $errTail"
    }

    Write-HueyStartLog "Huey consumer active PID $($proc.Id) (logs en consola del proceso; errores previos en $logErr si existen)"
}

try {
    if ($SkipMutex -or -not (Get-Command Invoke-MultishopStartMutex -ErrorAction SilentlyContinue)) {
        Start-MultishopHueyConsumer -NodoDirPath $NodoDir
    } else {
        Invoke-MultishopStartMutex -Name "Huey" -ScriptBlock { Start-MultishopHueyConsumer -NodoDirPath $NodoDir }
    }
} catch {
    Write-HueyStartLog "ERROR: $($_.Exception.Message)"
    throw
}
