# Starts the nodo Huey consumer (outbox + catalog sync jobs) in the background.
param(
    [string]$NodoDir = ""
)

$ErrorActionPreference = "Stop"
$DeployDir = Join-Path $env:ProgramData "Multishop"
$DirFile = Join-Path $DeployDir "nodo-dir.txt"
$StartLog = Join-Path $DeployDir "nodo-huey-start.log"

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
    $nodoLower = $NodoDirPath.TrimEnd('\').ToLowerInvariant()
    foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue) {
        $cmd = ($wp.CommandLine -as [string])
        if (-not $cmd) { continue }
        if ($cmd.ToLowerInvariant() -notlike "*$nodoLower*") { continue }
        if ($cmd -match 'huey\.bin\.huey_consumer|huey_consumer') {
            return [int]$wp.ProcessId
        }
    }
    return 0
}

try {
    Write-HueyStartLog "=== huey launcher user=$env:USERNAME session=$env:SESSIONNAME ==="

    if (-not $NodoDir -and (Test-Path $DirFile)) {
        $NodoDir = (Get-Content -LiteralPath $DirFile -Raw).Trim()
    }
    if (-not $NodoDir) {
        throw "NodoDir not set (missing nodo-dir.txt in ProgramData\Multishop)"
    }
    if (-not (Test-Path -LiteralPath $NodoDir)) {
        throw "NodoDir does not exist: $NodoDir"
    }

    $existingPid = Test-HueyConsumerRunning -NodoDirPath $NodoDir
    if ($existingPid -gt 0) {
        Write-HueyStartLog "Huey consumer already running PID $existingPid; skip."
        exit 0
    }

    $venvPython = Join-Path $NodoDir "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Missing venv python: $venvPython"
    }

    $logOut = Join-Path $DeployDir "nodo-huey.out.log"
    $logErr = Join-Path $DeployDir "nodo-huey.err.log"

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    Write-HueyStartLog "Starting: $venvPython -m huey.bin.huey_consumer huey_tasks.huey (cwd $NodoDir)"

    $proc = Start-Process -FilePath $venvPython `
        -ArgumentList @("-m", "huey.bin.huey_consumer", "huey_tasks.huey") `
        -WorkingDirectory $NodoDir `
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
} catch {
    Write-HueyStartLog "ERROR: $($_.Exception.Message)"
    throw
}
