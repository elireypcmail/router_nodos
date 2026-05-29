# Lectura de .env del nodo (NODO_PORT, etc.) — dot-source desde otros scripts en scripts\

function Read-MultishopEnvFile {
    param([string]$Path)
    $map = @{}
    if (-not $Path) { return $map }
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    $lines = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue
    foreach ($raw in $lines) {
        $line = ($raw -as [string])
        if (-not $line) { continue }
        $line = $line.Trim()
        if (-not $line) { continue }
        if ($line.StartsWith("#")) { continue }
        $idx = $line.IndexOf("=")
        if ($idx -le 0) { continue }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim()
        if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        if ($k) {
            $map[$k] = $v
        }
    }
    return $map
}

function Get-MultishopNodoDirFromProgramData {
    $dirFile = Join-Path $env:ProgramData "Multishop\nodo-dir.txt"
    if (-not (Test-Path -LiteralPath $dirFile)) {
        return $null
    }
    $dir = (Get-Content -LiteralPath $dirFile -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not $dir) { return $null }
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    return $dir
}

function Get-MultishopNodoApiPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,

        [int]$DefaultPort = 8443
    )
    $envPath = Join-Path $NodoDir ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        return $DefaultPort
    }
    $map = Read-MultishopEnvFile -Path $envPath
    $raw = $map["NODO_PORT"]
    if (-not $raw) {
        return $DefaultPort
    }
    $parsed = 0
    if ([int]::TryParse($raw.Trim(), [ref]$parsed) -and $parsed -gt 0 -and $parsed -le 65535) {
        return $parsed
    }
    Write-Warning "NODO_PORT invalido en .env ($raw); usando $DefaultPort"
    return $DefaultPort
}

function Test-IsMultishopNodoProcess {
    param(
        [AllowNull()][string]$CommandLine,
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $cmdLower = $CommandLine.ToLowerInvariant()
    $nodoLower = $NodoDir.TrimEnd('\').ToLowerInvariant()
    if ($cmdLower -notlike "*$nodoLower*") {
        return $false
    }
    if ($cmdLower -match '(^|\s|")main\.py(\s|$|")') {
        return $true
    }
    if ($cmdLower -match 'huey\.bin\.huey_consumer') {
        return $true
    }
    if ($cmdLower -match 'huey_consumer') {
        return $true
    }
    return $false
}

function Test-MultishopNodoApiProcessRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue) {
        $cmd = ($wp.CommandLine -as [string])
        if (-not $cmd) { continue }
        if (-not (Test-IsMultishopNodoProcess -CommandLine $cmd -NodoDir $NodoDir)) { continue }
        if ($cmd -match 'main\.py') {
            return [int]$wp.ProcessId
        }
    }
    return 0
}

function Stop-MultishopNodoProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $nodoDir = $NodoDir.TrimEnd('\')
    $apiPort = Get-MultishopNodoApiPort -NodoDir $nodoDir
    $stoppedIds = @{}

    $pythonProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('python.exe', 'pythonw.exe') }

    foreach ($wp in $pythonProcs) {
        if (-not (Test-IsMultishopNodoProcess -CommandLine $wp.CommandLine -NodoDir $nodoDir)) {
            continue
        }
        Write-Host "Stopping Multishop nodo PID $($wp.ProcessId) ..."
        Stop-Process -Id $wp.ProcessId -Force -ErrorAction SilentlyContinue
        $stoppedIds[$wp.ProcessId] = $true
    }

    try {
        $listeners = @(
            Get-NetTCPConnection -LocalPort $apiPort -State Listen -ErrorAction SilentlyContinue
        ) | Where-Object { $_ }
        foreach ($conn in $listeners) {
            $procId = $conn.OwningProcess
            if (-not $procId -or $stoppedIds.ContainsKey($procId)) {
                continue
            }
            $wp = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
            if ($wp -and (Test-IsMultishopNodoProcess -CommandLine $wp.CommandLine -NodoDir $nodoDir)) {
                Write-Host "Stopping Multishop API PID $procId (port $apiPort) ..."
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $stoppedIds[$procId] = $true
            } else {
                Write-Host "Skipping PID $procId on port $apiPort (not Multishop nodo API)."
            }
        }
    } catch {
        # Get-NetTCPConnection may be unavailable on some Windows editions
    }

    if ($stoppedIds.Count -gt 0) {
        Start-Sleep -Seconds 2
    }
}
