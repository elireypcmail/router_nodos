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
    $counts = Get-MultishopNodoLeaderCounts -NodoDir $NodoDir
    if ($counts.Api -lt 1) { return 0 }
    foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue) {
        $cmd = ($wp.CommandLine -as [string])
        if (-not $cmd) { continue }
        if ($cmd -notmatch 'main\.py') { continue }
        if (-not (Test-IsMultishopNodoProcess -CommandLine $cmd -NodoDir $NodoDir)) { continue }
        $parentId = [int]$wp.ParentProcessId
        if ($parentId -gt 0) {
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction SilentlyContinue
            $parentCmd = ($parent.CommandLine -as [string])
            if ($parentCmd -and (Test-IsMultishopNodoProcess -CommandLine $parentCmd -NodoDir $NodoDir) -and $parentCmd -match 'main\.py') {
                continue
            }
        }
        return [int]$wp.ProcessId
    }
    return 0
}

function Test-MultishopHueyProcessRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $counts = Get-MultishopNodoLeaderCounts -NodoDir $NodoDir
    if ($counts.Huey -lt 1) { return 0 }
    foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue) {
        $cmd = ($wp.CommandLine -as [string])
        if (-not $cmd) { continue }
        if ($cmd -notmatch 'huey_consumer') { continue }
        if (-not (Test-IsMultishopNodoProcess -CommandLine $cmd -NodoDir $NodoDir)) { continue }
        $parentId = [int]$wp.ParentProcessId
        if ($parentId -gt 0) {
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction SilentlyContinue
            $parentCmd = ($parent.CommandLine -as [string])
            if ($parentCmd -and (Test-IsMultishopNodoProcess -CommandLine $parentCmd -NodoDir $NodoDir) -and $parentCmd -match 'huey_consumer') {
                continue
            }
        }
        return [int]$wp.ProcessId
    }
    return 0
}

function Get-MultishopNodoProcessCounts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    return (Get-MultishopNodoLeaderCounts -NodoDir $NodoDir)
}

function Get-MultishopNodoLeaderCounts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $nodoLower = $NodoDir.TrimEnd('\').ToLowerInvariant()
    $matches = @()
    foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue) {
        $cmd = ($wp.CommandLine -as [string])
        if (-not $cmd) { continue }
        if ($cmd.ToLowerInvariant() -notlike "*$nodoLower*") { continue }
        $kind = $null
        if ($cmd -match 'main\.py') { $kind = 'api' }
        elseif ($cmd -match 'huey_consumer') { $kind = 'huey' }
        if (-not $kind) { continue }
        $matches += [PSCustomObject]@{
            ProcessId = [int]$wp.ProcessId
            ParentProcessId = [int]$wp.ParentProcessId
            Kind = $kind
            CommandLine = $cmd
        }
    }

    $api = 0
    $huey = 0
    foreach ($m in $matches) {
        $parentIsNodoPython = $false
        if ($m.ParentProcessId -gt 0) {
            $parent = $matches | Where-Object { $_.ProcessId -eq $m.ParentProcessId } | Select-Object -First 1
            if ($parent) {
                $parentIsNodoPython = $true
            }
        }
        if ($parentIsNodoPython) { continue }
        if ($m.Kind -eq 'api') { $api++ } else { $huey++ }
    }
    return @{ Api = $api; Huey = $huey }
}

function Wait-MultishopNodoProcessesStopped {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,
        [int]$TimeoutSec = 25
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $counts = Get-MultishopNodoLeaderCounts -NodoDir $NodoDir
        if ($counts.Api -eq 0 -and $counts.Huey -eq 0) {
            return $true
        }
        Stop-MultishopNodoProcesses -NodoDir $NodoDir
        Start-Sleep -Seconds 1
    }
    return $false
}

function Set-MultishopOnStartTasksEnabled {
    param([bool]$Enabled)
    foreach ($name in @('Multishop-Nodo-API', 'Multishop-Nodo-Huey')) {
        if (-not (Test-MultishopScheduledTaskExists -Name $name)) { continue }
        if ($Enabled) {
            if (Get-Command Enable-ScheduledTask -ErrorAction SilentlyContinue) {
                Enable-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue | Out-Null
            }
            Invoke-MultishopSchTasksQuiet @("/Change", "/TN", $name, "/ENABLE") | Out-Null
        } else {
            Disable-MultishopScheduledTaskNamed -Name $name | Out-Null
        }
    }
}

function Invoke-PrepareMultishopStartNow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDirPath
    )
    Write-Host "Preparando arranque unico (legacy off + stop + espera) ..."
    Disable-MultishopLogonTasks | Out-Null
    Remove-MultishopNodoScheduledTasks -Scope LogonOnly -Quiet | Out-Null
    Set-MultishopOnStartTasksEnabled -Enabled $false
    Stop-MultishopNodoProcesses -NodoDir $NodoDirPath
    if (-not (Wait-MultishopNodoProcessesStopped -NodoDir $NodoDirPath)) {
        Write-Warning "Algunos procesos Multishop siguen activos tras espera; continuando."
    }
}

function Invoke-MultishopSchTasksQuiet {
    param([string[]]$ArgumentList)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $null = schtasks.exe @ArgumentList 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
}

function Get-MultishopScheduledTaskPlainName {
    param([string]$Name)
    return (($Name -replace '^\\', '').Trim())
}

function Test-MultishopScheduledTaskExists {
    param([string]$Name)
    $plain = Get-MultishopScheduledTaskPlainName -Name $Name
    if (-not $plain) { return $false }
    if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
        $task = Get-ScheduledTask -TaskName $plain -TaskPath '\' -ErrorAction SilentlyContinue
        if ($task) { return $true }
    }
    foreach ($tn in @($plain, "\$plain")) {
        if (Invoke-MultishopSchTasksQuiet @("/Query", "/TN", $tn) -eq 0) {
            return $true
        }
    }
    return $false
}

function Disable-MultishopScheduledTaskNamed {
    param([string]$Name)
    $plain = Get-MultishopScheduledTaskPlainName -Name $Name
    if (-not $plain) { return $false }
    if (-not (Test-MultishopScheduledTaskExists -Name $plain)) { return $false }

    $disabled = $false
    if (Get-Command Disable-ScheduledTask -ErrorAction SilentlyContinue) {
        try {
            Disable-ScheduledTask -TaskName $plain -TaskPath '\' -ErrorAction Stop | Out-Null
            $disabled = $true
        } catch {
            $disabled = $false
        }
    }
    foreach ($tn in @($plain, "\$plain")) {
        if (Invoke-MultishopSchTasksQuiet @("/Change", "/TN", $tn, "/DISABLE") -eq 0) {
            $disabled = $true
        }
    }
    return $disabled
}

function Disable-MultishopLogonTasks {
    $count = 0
    foreach ($n in @('Multishop-Nodo-API-Logon', 'Multishop-Nodo-Huey-Logon')) {
        if (Disable-MultishopScheduledTaskNamed -Name $n) {
            Write-Host "  Logon deshabilitada: $n"
            $count++
        }
    }
    return $count
}

function Remove-MultishopScheduledTaskNamed {
    param([string]$Name)
    $plain = Get-MultishopScheduledTaskPlainName -Name $Name
    if (-not $plain) { return $false }
    if (-not (Test-MultishopScheduledTaskExists -Name $plain)) {
        return $false
    }

    Disable-MultishopScheduledTaskNamed -Name $plain | Out-Null

    $removed = $false
    if (Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue) {
        try {
            if (Get-Command Stop-ScheduledTask -ErrorAction SilentlyContinue) {
                Stop-ScheduledTask -TaskName $plain -TaskPath '\' -ErrorAction SilentlyContinue | Out-Null
                Start-Sleep -Milliseconds 500
            }
            Unregister-ScheduledTask -TaskName $plain -TaskPath '\' -Confirm:$false -ErrorAction Stop
            $removed = $true
        } catch {
            $removed = $false
        }
    }

    if (-not $removed) {
        foreach ($tn in @($plain, "\$plain")) {
            if (Invoke-MultishopSchTasksQuiet @("/Query", "/TN", $tn) -ne 0) { continue }
            Invoke-MultishopSchTasksQuiet @("/End", "/TN", $tn) | Out-Null
            Start-Sleep -Milliseconds 500
            if (Invoke-MultishopSchTasksQuiet @("/Delete", "/TN", $tn, "/F") -eq 0) {
                $removed = $true
                break
            }
        }
    }

    if ($removed -and (Test-MultishopScheduledTaskExists -Name $plain)) {
        return $false
    }
    return $removed
}

function Remove-MultishopNodoScheduledTasks {
    param(
        [ValidateSet('All', 'LogonOnly', 'OnStartOnly')]
        [string]$Scope = 'All',

        [switch]$Quiet
    )
    $names = switch ($Scope) {
        'LogonOnly' { @('Multishop-Nodo-API-Logon', 'Multishop-Nodo-Huey-Logon') }
        'OnStartOnly' { @('Multishop-Nodo-API', 'Multishop-Nodo-Huey') }
        default { @(
                'Multishop-Nodo-API',
                'Multishop-Nodo-API-Logon',
                'Multishop-Nodo-Huey',
                'Multishop-Nodo-Huey-Logon'
            ) }
    }
    $count = 0
    foreach ($n in $names) {
        if (Remove-MultishopScheduledTaskNamed -Name $n) {
            $count++
            if (-not $Quiet) {
                Write-Host "  Tarea eliminada: $n"
            }
        }
    }
    return $count
}

function Invoke-MultishopStartMutex {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [scriptblock]$ScriptBlock,

        [int]$TimeoutMs = 120000
    )
    $mutexName = "Global\Multishop-Nodo-$Name"
    $mutex = New-Object System.Threading.Mutex($false, $mutexName)
    $acquired = $false
    try {
        $acquired = $mutex.WaitOne($TimeoutMs)
        if (-not $acquired) {
            throw "Timeout esperando mutex $mutexName ($TimeoutMs ms)"
        }
        & $ScriptBlock
    } finally {
        if ($acquired) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        $mutex.Dispose()
    }
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
