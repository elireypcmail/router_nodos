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
    $nodoPythonProcs = @()
    foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue) {
        $cmd = ($wp.CommandLine -as [string])
        if (-not $cmd) { continue }
        if ($cmd.ToLowerInvariant() -notlike "*$nodoLower*") { continue }
        $kind = $null
        if ($cmd -match 'main\.py') { $kind = 'api' }
        elseif ($cmd -match 'huey_consumer') { $kind = 'huey' }
        if (-not $kind) { continue }
        $nodoPythonProcs += [PSCustomObject]@{
            ProcessId = [int]$wp.ProcessId
            ParentProcessId = [int]$wp.ParentProcessId
            Kind = $kind
            CommandLine = $cmd
        }
    }

    $api = 0
    $huey = 0
    foreach ($m in $nodoPythonProcs) {
        $parentIsNodoPython = $false
        if ($m.ParentProcessId -gt 0) {
            $parent = $nodoPythonProcs | Where-Object { $_.ProcessId -eq $m.ParentProcessId } | Select-Object -First 1
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
    Write-Host "Preparando arranque (ONSTART off + stop procesos) ..."
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

function Get-MultishopScheduledTaskEntries {
    param([string]$Name)
    $plain = Get-MultishopScheduledTaskPlainName -Name $Name
    if (-not $plain) { return @() }

    foreach ($tn in @($plain, "\$plain")) {
        if (Invoke-MultishopSchTasksQuiet @("/Query", "/TN", $tn) -eq 0) {
            return @([PSCustomObject]@{
                    TaskName = $plain
                    TaskPath = '\'
                })
        }
    }

    if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
        $task = Get-ScheduledTask -TaskName $plain -TaskPath '\' -ErrorAction SilentlyContinue
        if ($task) { return @($task) }
    }
    return @()
}

function Test-MultishopScheduledTaskExists {
    param([string]$Name)
    return ((Get-MultishopScheduledTaskEntries -Name $Name).Count -gt 0)
}

function Disable-MultishopScheduledTaskNamed {
    param([string]$Name)
    $plain = Get-MultishopScheduledTaskPlainName -Name $Name
    if (-not $plain) { return $false }
    $entries = Get-MultishopScheduledTaskEntries -Name $plain
    if ($entries.Count -eq 0) { return $false }

    $disabled = $false
    foreach ($entry in $entries) {
        $taskName = $entry.TaskName
        $taskPath = if ($entry.TaskPath) { $entry.TaskPath } else { '\' }
        if (Get-Command Disable-ScheduledTask -ErrorAction SilentlyContinue) {
            try {
                Disable-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop | Out-Null
                $disabled = $true
            } catch {
                # fallback schtasks
            }
        }
        foreach ($tn in @("$taskPath$taskName", $taskName, "\$taskName") | Select-Object -Unique) {
            if (-not $tn) { continue }
            if (Invoke-MultishopSchTasksQuiet @("/Change", "/TN", $tn, "/DISABLE") -eq 0) {
                $disabled = $true
            }
        }
    }
    return $disabled
}

function Get-MultishopSchTasksTnCandidates {
    param(
        [string]$TaskPath,
        [string]$TaskName
    )
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $plain = Get-MultishopScheduledTaskPlainName -Name $TaskName
    if (-not $plain) { return @() }
    if ($TaskPath -and $TaskPath -ne '\') {
        $full = ($TaskPath.TrimEnd('\') + '\' + $plain)
        [void]$candidates.Add($full)
    }
    [void]$candidates.Add("\$plain")
    [void]$candidates.Add($plain)
    return @($candidates | Select-Object -Unique)
}

function Remove-MultishopScheduledTaskNamed {
    param(
        [string]$Name,
        [switch]$VerboseFail
    )
    $plain = Get-MultishopScheduledTaskPlainName -Name $Name
    if (-not $plain) { return $false }
    if (-not (Test-MultishopScheduledTaskExists -Name $plain)) {
        return $false
    }

    Disable-MultishopScheduledTaskNamed -Name $plain | Out-Null
    $removedAny = $false
    $lastErr = ""
    $entries = Get-MultishopScheduledTaskEntries -Name $plain
    if ($entries.Count -eq 0) {
        $entries = @([PSCustomObject]@{ TaskName = $plain; TaskPath = '\' })
    }

    foreach ($entry in $entries) {
        $taskName = $entry.TaskName
        $taskPath = if ($entry.TaskPath) { $entry.TaskPath } else { '\' }

        if (Get-Command Stop-ScheduledTask -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue | Out-Null
            Start-Sleep -Milliseconds 400
        }

        $entryRemoved = $false
        if (Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue) {
            try {
                Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false -ErrorAction Stop
                $entryRemoved = $true
            } catch {
                $lastErr = $_.Exception.Message
            }
        }

        if (-not $entryRemoved) {
            foreach ($tn in (Get-MultishopSchTasksTnCandidates -TaskPath $taskPath -TaskName $taskName)) {
                if (-not $tn) { continue }
                if (Invoke-MultishopSchTasksQuiet @("/Query", "/TN", $tn) -ne 0) { continue }
                Invoke-MultishopSchTasksQuiet @("/End", "/TN", $tn) | Out-Null
                Start-Sleep -Milliseconds 400
                if (Invoke-MultishopSchTasksQuiet @("/Delete", "/TN", $tn, "/F") -eq 0) {
                    $entryRemoved = $true
                    break
                }
            }
        }

        if ($entryRemoved) {
            $removedAny = $true
        }
    }

    if (-not (Test-MultishopScheduledTaskExists -Name $plain)) {
        return $true
    }

    if (-not $removedAny -and $VerboseFail -and $lastErr) {
        Write-Warning "No se pudo eliminar tarea $plain : $lastErr"
    }
    return $removedAny
}

function Remove-MultishopNodoScheduledTasks {
    param(
        [switch]$Quiet
    )
    $names = @('Multishop-Nodo-API', 'Multishop-Nodo-Huey')
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

function Get-ProtectedMultishopCallerProcessIds {
    $protected = New-Object 'System.Collections.Generic.HashSet[int]'
    [void]$protected.Add($PID)
    try {
        $currentId = $PID
        for ($i = 0; $i -lt 12; $i++) {
            $wp = Get-CimInstance Win32_Process -Filter "ProcessId=$currentId" -ErrorAction SilentlyContinue
            if (-not $wp) { break }
            $parentId = [int]$wp.ParentProcessId
            if ($parentId -le 0) { break }
            if (-not $protected.Add($parentId)) { break }
            $currentId = $parentId
        }
    } catch {
        # ignore
    }
    return @($protected)
}

function Test-IsMultishopNodoServiceLauncher {
    param([AllowNull()][string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $cmdLower = $CommandLine.ToLowerInvariant()

    if ($cmdLower -match '\bwscript(\.exe)?\b' -and $cmdLower -match 'programdata\\multishop\\start-nodo-(api|huey)\.vbs') {
        return $true
    }

    if ($cmdLower -notmatch '\bpowershell(\.exe)?\b') {
        return $false
    }

    if ($cmdLower -match 'start-nodo-(api|huey)\.ps1') {
        return $true
    }

    if ($cmdLower -match 'programdata\\multishop\\start-nodo-(api|huey)\.ps1') {
        return $true
    }

    return $false
}

function Stop-MultishopNodoLaunchers {
    param([string]$NodoDir)
    $protectedIds = Get-ProtectedMultishopCallerProcessIds
    foreach ($procName in @('wscript.exe', 'powershell.exe')) {
        foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='$procName'" -ErrorAction SilentlyContinue) {
            $procId = [int]$wp.ProcessId
            if ($protectedIds -contains $procId) { continue }
            $cmd = ($wp.CommandLine -as [string])
            if (-not (Test-IsMultishopNodoServiceLauncher -CommandLine $cmd)) { continue }
            Write-Host "Stopping Multishop launcher PID $procId ($procName) ..."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-MultishopNodoProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,

        [switch]$SkipLaunchers
    )
    $nodoDir = $NodoDir.TrimEnd('\')
    $apiPort = Get-MultishopNodoApiPort -NodoDir $nodoDir
    $stoppedIds = @{}

    if (-not $SkipLaunchers) {
        Stop-MultishopNodoLaunchers -NodoDir $nodoDir
    }

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
        Stop-MultishopNodoLaunchers -NodoDir $nodoDir
    }
}

function Test-MultishopNodoApiTcpPortListening {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            return $true
        }
    } catch {
        # Get-NetTCPConnection no disponible en algunas ediciones Windows
    }
    $pattern = ":$Port\s"
    $netstat = netstat -ano 2>$null | Select-String $pattern
    return ($null -ne $netstat)
}

function Test-MultishopNodoApiPortListening {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $port = Get-MultishopNodoApiPort -NodoDir $NodoDir
    return (Test-MultishopNodoApiTcpPortListening -Port $port)
}

function Wait-MultishopNodoApiPortListening {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,
        [int]$TimeoutSec = 45,
        [int]$IntervalSec = 2
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-MultishopNodoApiPortListening -NodoDir $NodoDir) {
            return $true
        }
        Start-Sleep -Seconds $IntervalSec
    }
    return $false
}

function Get-MultishopHueyStartFailureHint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $lines = @("NodoDir: $NodoDir")
    foreach ($base in @($env:ProgramData, $env:LOCALAPPDATA)) {
        if (-not $base) { continue }
        $logDir = Join-Path $base "Multishop"
        foreach ($name in @("nodo-huey.err.log", "nodo-huey-start.log", "nodo-huey.out.log")) {
            $path = Join-Path $logDir $name
            if (-not (Test-Path -LiteralPath $path)) { continue }
            $tail = (Get-Content -LiteralPath $path -Tail 12 -ErrorAction SilentlyContinue) -join " | "
            if ($tail) {
                $lines += "$path -> $tail"
            }
        }
    }
    $dataDir = Join-Path $NodoDir "data"
    $lines += "Data dir: $dataDir (HUEY_DB_PATH / SYNC_DB_PATH en .env)"
    return ($lines -join "`n  ")
}

function Ensure-NodoWritableDataDir {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $dataDir = Join-Path $NodoDir.TrimEnd('\') "data"
    if (-not (Test-Path -LiteralPath $dataDir)) {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    }
    $inherit = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit,ObjectInherit"
    $propagate = [System.Security.AccessControl.PropagationFlags]::None
    $acl = Get-Acl -LiteralPath $dataDir
    $acl.SetAccessRuleProtection($false, $true)
    foreach ($entry in @(
            @{ Sid = "S-1-5-18"; Rights = "Modify" },
            @{ Sid = "S-1-5-32-544"; Rights = "FullControl" },
            @{ Sid = "S-1-5-32-545"; Rights = "Modify" }
        )) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            ([System.Security.Principal.SecurityIdentifier]$entry.Sid),
            $entry.Rights,
            $inherit,
            $propagate,
            "Allow"
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $dataDir -AclObject $acl
    & icacls.exe $dataDir /grant "*S-1-5-18:(OI)(CI)M" /T /C 2>$null | Out-Null
    & icacls.exe $dataDir /grant "*S-1-5-32-544:(OI)(CI)F" /T /C 2>$null | Out-Null
    & icacls.exe $dataDir /grant "*S-1-5-32-545:(OI)(CI)M" /T /C 2>$null | Out-Null
}

function Wait-MultishopHueyProcessRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,
        [int]$TimeoutSec = 45,
        [int]$IntervalSec = 2
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $pid = Test-MultishopHueyProcessRunning -NodoDir $NodoDir
        if ($pid -gt 0) {
            return $pid
        }
        Start-Sleep -Seconds $IntervalSec
    }
    return 0
}

function Get-MultishopNodoApiStartFailureHint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $port = Get-MultishopNodoApiPort -NodoDir $NodoDir
    $lines = @("Puerto esperado: $port (NODO_PORT en .env)")
    foreach ($base in @($env:ProgramData, $env:LOCALAPPDATA)) {
        if (-not $base) { continue }
        $logDir = Join-Path $base "Multishop"
        foreach ($name in @("nodo-api.err.log", "nodo-api-start.log", "nodo-api.out.log")) {
            $path = Join-Path $logDir $name
            if (-not (Test-Path -LiteralPath $path)) { continue }
            $tail = (Get-Content -LiteralPath $path -Tail 10 -ErrorAction SilentlyContinue) -join " | "
            if ($tail) {
                $lines += "$path -> $tail"
            }
        }
    }
    return ($lines -join "`n  ")
}
