# Lectura de .env del nodo (NODO_PORT, etc.) — dot-source desde otros scripts en scripts\
#
# Fork "router": convive con Multishop\nodo en la misma PC (rutas y tareas distintas).

$script:MultishopProductId = 'router'
$script:MultishopInstallFolderName = 'router'

function Get-MultishopProductId {
    if ($script:MultishopProductId) { return $script:MultishopProductId }
    return 'router'
}

function Get-MultishopInstallFolderName {
    if ($script:MultishopInstallFolderName) { return $script:MultishopInstallFolderName }
    return 'router'
}

function Get-MultishopDefaultInstallRoot {
    return Join-Path ${env:ProgramFiles} (Join-Path 'Multishop' (Get-MultishopInstallFolderName))
}

function Get-MultishopProgramDataRoot {
    return Join-Path $env:ProgramData 'Multishop'
}

function Get-MultishopDeployRoot {
    return Join-Path (Get-MultishopProgramDataRoot) (Get-MultishopProductId)
}

function Get-MultishopDirFileName {
    return "$(Get-MultishopProductId)-dir.txt"
}

function Get-MultishopDirFilePath {
    return Join-Path (Get-MultishopDeployRoot) (Get-MultishopDirFileName)
}

function Get-MultishopScheduledTaskNames {
    $id = Get-MultishopProductId
    $label = (Get-Culture).TextInfo.ToTitleCase($id)
    return @(
        "Multishop-$label-API",
        "Multishop-$label-Huey"
    )
}

function Get-MultishopApiScheduledTaskName {
    return (Get-MultishopScheduledTaskNames)[0]
}

function Get-MultishopHueyScheduledTaskName {
    return (Get-MultishopScheduledTaskNames)[1]
}

function Get-MultishopApiLogBasename {
    return "$(Get-MultishopProductId)-api"
}

function Get-MultishopLauncherBasename {
    return 'start-api'
}

function Get-MultishopHueyLauncherBasename {
    return 'start-huey'
}

function Get-MultishopStartMutexPrefix {
    $id = Get-MultishopProductId
    $label = (Get-Culture).TextInfo.ToTitleCase($id)
    return "Global\Multishop-$label"
}

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
    $dirFile = Get-MultishopDirFilePath
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
    foreach ($name in (Get-MultishopScheduledTaskNames)) {
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
    Write-Host "Preparando arranque router (solo procesos/tareas de este producto) ..."
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
    $names = Get-MultishopScheduledTaskNames
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
    $mutexName = "$(Get-MultishopStartMutexPrefix)-$Name"
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

function Get-MultishopProductLauncherPathPatterns {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $folder = (Split-Path $NodoDir.TrimEnd('\') -Leaf).ToLowerInvariant()
    switch ($folder) {
        'router' {
            return @(
                'programdata\\multishop\\router\\start-api\.(vbs|ps1)'
                'programdata\\multishop\\router\\start-huey\.(vbs|ps1)'
            )
        }
        'nodo' {
            return @(
                'programdata\\multishop\\start-nodo-api\.(vbs|ps1)'
                'programdata\\multishop\\start-nodo-huey\.(vbs|ps1)'
                'programdata\\multishop\\nodo\\start-api\.(vbs|ps1)'
                'programdata\\multishop\\nodo\\start-huey\.(vbs|ps1)'
            )
        }
        default {
            $deploy = $null
            if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) {
                $deploy = (Get-MultishopDeployRoot).ToLowerInvariant()
            }
            if ($deploy -and $NodoDir.TrimEnd('\').ToLowerInvariant() -like "*\multishop\$folder") {
                $escaped = [regex]::Escape($deploy).Replace('\\', '\\\\')
                return @(
                    "$escaped\\start-api\.(vbs|ps1)"
                    "$escaped\\start-huey\.(vbs|ps1)"
                    "$escaped\\start-nodo-api\.(vbs|ps1)"
                    "$escaped\\start-nodo-huey\.(vbs|ps1)"
                )
            }
            $nodoEscaped = [regex]::Escape($NodoDir.TrimEnd('\').ToLowerInvariant())
            return @("$nodoEscaped")
        }
    }
}

function Test-IsMultishopProductLauncher {
    param(
        [AllowNull()][string]$CommandLine,
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $cmdLower = $CommandLine.ToLowerInvariant()
    if ($cmdLower -notmatch '\b(wscript|powershell)(\.exe)?\b') {
        return $false
    }
    foreach ($pattern in (Get-MultishopProductLauncherPathPatterns -NodoDir $NodoDir)) {
        if ($cmdLower -match $pattern) {
            return $true
        }
    }
    return $false
}

function Test-IsMultishopNodoServiceLauncher {
    param(
        [AllowNull()][string]$CommandLine,
        [string]$NodoDir = ""
    )
    if ($NodoDir) {
        return (Test-IsMultishopProductLauncher -CommandLine $CommandLine -NodoDir $NodoDir)
    }
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $cmdLower = $CommandLine.ToLowerInvariant()
    if ($cmdLower -notmatch '\b(wscript|powershell)(\.exe)?\b') {
        return $false
    }
    return ($cmdLower -match 'programdata\\multishop\\')
}

function Stop-MultishopNodoLaunchers {
    param([string]$NodoDir)
    if (-not $NodoDir) { return }
    $protectedIds = Get-ProtectedMultishopCallerProcessIds
    foreach ($procName in @('wscript.exe', 'powershell.exe')) {
        foreach ($wp in Get-CimInstance Win32_Process -Filter "Name='$procName'" -ErrorAction SilentlyContinue) {
            $procId = [int]$wp.ProcessId
            if ($protectedIds -contains $procId) { continue }
            $cmd = ($wp.CommandLine -as [string])
            if (-not (Test-IsMultishopProductLauncher -CommandLine $cmd -NodoDir $NodoDir)) { continue }
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

function Stop-MultishopNodoApiLeaderProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,
        [string]$Reason = ""
    )
    $apiPid = Test-MultishopNodoApiProcessRunning -NodoDir $NodoDir
    if ($apiPid -le 0) {
        return $false
    }
    $msg = "Stopping stale Multishop API PID $apiPid"
    if ($Reason) {
        $msg += " ($Reason)"
    }
    Write-Host "$msg ..."
    Stop-Process -Id $apiPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    return $true
}

function Test-MultishopNodoApiHealthy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    if (-not (Test-MultishopNodoApiPortListening -NodoDir $NodoDir)) {
        return $false
    }
    return ((Test-MultishopNodoApiProcessRunning -NodoDir $NodoDir) -gt 0)
}

function Wait-MultishopNodoApiProcessRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,
        [int]$TimeoutSec = 45,
        [int]$IntervalSec = 2
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $runningPid = Test-MultishopNodoApiProcessRunning -NodoDir $NodoDir
        if ($runningPid -gt 0) {
            return $runningPid
        }
        Start-Sleep -Seconds $IntervalSec
    }
    return 0
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

function Test-PythonPathIsMachineWide {
    param([string]$Path)
    if (-not $Path) { return $false }
    $norm = $Path.TrimEnd('\')
    if ($norm -match '(?i)[\\/](Users|AppData)[\\/]') { return $false }
    return $true
}

function Get-VenvPyvenvHome {
    param([string]$VenvDir)
    $cfg = Join-Path $VenvDir "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $cfg)) { return $null }
    foreach ($line in Get-Content -LiteralPath $cfg -ErrorAction SilentlyContinue) {
        if ($line -match '^\s*home\s*=\s*(.+)$') {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Test-VenvPythonHasPip {
    param([string]$VenvPythonExe)
    if (-not (Test-Path -LiteralPath $VenvPythonExe)) { return $false }
    try {
        & $VenvPythonExe -m pip --version 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Test-VenvIsHealthyForSystemAutostart {
    param(
        [string]$VenvDir,
        [string]$VenvPythonExe
    )
    if (-not (Test-Path -LiteralPath $VenvPythonExe)) { return $false }
    $home = Get-VenvPyvenvHome -VenvDir $VenvDir
    if ($home -and -not (Test-PythonPathIsMachineWide -Path $home)) {
        return $false
    }
    if (-not (Test-VenvPythonHasPip -VenvPythonExe $VenvPythonExe)) {
        return $false
    }
    return $true
}

function Ensure-NodoVenvSystemAccess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VenvDir
    )
    if (-not (Test-Path -LiteralPath $VenvDir)) { return }
    & icacls.exe $VenvDir /grant "*S-1-5-18:(OI)(CI)RX" /T /C 2>$null | Out-Null
    & icacls.exe $VenvDir /grant "*S-1-5-32-544:(OI)(CI)F" /T /C 2>$null | Out-Null
    & icacls.exe $VenvDir /grant "*S-1-5-32-545:(OI)(CI)RX" /T /C 2>$null | Out-Null
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
        # No usar $pid: en PowerShell es alias de solo lectura de $PID (proceso actual).
        $runningHueyPid = Test-MultishopHueyProcessRunning -NodoDir $NodoDir
        if ($runningHueyPid -gt 0) {
            return $runningHueyPid
        }
        Start-Sleep -Seconds $IntervalSec
    }
    return 0
}

function Test-MultishopEnvFlagTrue {
    param([AllowNull()][string]$Value)
    if (-not $Value) { return $false }
    return ($Value.Trim() -match '^(?i:true|1|yes)$')
}

function Test-MultishopNodoNeedsMysqlAtStartup {
    param([hashtable]$EnvMap)
    if (-not $EnvMap) { return $false }
    if (-not $EnvMap["MYSQL_USER"] -or -not $EnvMap["MYSQL_DATABASE"]) {
        return $false
    }
    if (Test-MultishopEnvFlagTrue -Value $EnvMap["HUEY_ENABLED"]) { return $true }
    if (Test-MultishopEnvFlagTrue -Value $EnvMap["HUB_PUSH_ENABLED"]) { return $true }
    return $false
}

function Wait-MultishopNodoMysqlReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,
        [int]$MaxTries = 60,
        [double]$SleepSeconds = 2.0,
        [scriptblock]$LogFn = $null
    )
    $envPath = Join-Path $NodoDir ".env"
    $map = Read-MultishopEnvFile -Path $envPath
    if (-not (Test-MultishopNodoNeedsMysqlAtStartup -EnvMap $map)) {
        return $true
    }

    $python = Join-Path $NodoDir "venv\Scripts\python.exe"
    $waitScript = Join-Path $NodoDir "scripts\mysql_wait_ready.py"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Missing venv python: $python"
    }
    if (-not (Test-Path -LiteralPath $waitScript)) {
        if ($LogFn) { & $LogFn "mysql_wait_ready.py no encontrado; omitiendo espera MySQL" }
        return $true
    }

    $saved = @{}
    foreach ($key in @(
            "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE",
            "MYSQL_WAIT_TRIES", "MYSQL_WAIT_SLEEP"
        )) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
    }
    try {
        if ($map["MYSQL_HOST"]) { $env:MYSQL_HOST = $map["MYSQL_HOST"] }
        if ($map["MYSQL_PORT"]) { $env:MYSQL_PORT = $map["MYSQL_PORT"] } else { $env:MYSQL_PORT = "3306" }
        $env:MYSQL_USER = $map["MYSQL_USER"]
        $env:MYSQL_PASSWORD = $map["MYSQL_PASSWORD"]
        $env:MYSQL_DATABASE = $map["MYSQL_DATABASE"]
        $env:MYSQL_WAIT_TRIES = "$MaxTries"
        $env:MYSQL_WAIT_SLEEP = "$SleepSeconds"

        $hostPort = "$($env:MYSQL_HOST):$($env:MYSQL_PORT)"
        if ($LogFn) {
            & $LogFn "Esperando MySQL $hostPort (hasta $MaxTries intentos) ..."
        } else {
            Write-Host "Esperando MySQL $hostPort (hasta $MaxTries intentos) ..."
        }

        & $python $waitScript 2>&1 | ForEach-Object {
            $line = "$_"
            if ($LogFn) { & $LogFn $line } else { Write-Host $line }
        }
        if ($LASTEXITCODE -ne 0) {
            throw "MySQL no respondio en $hostPort tras $MaxTries intentos. Revise el servicio MySQL del ERP."
        }
        if ($LogFn) { & $LogFn "MySQL listo en $hostPort" }
        return $true
    } finally {
        foreach ($key in $saved.Keys) {
            if ($null -eq $saved[$key]) {
                Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
            } else {
                Set-Item -Path "Env:$key" -Value $saved[$key]
            }
        }
    }
}

function Get-MultishopNodoApiStartupWaitSeconds {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $map = Read-MultishopEnvFile -Path (Join-Path $NodoDir ".env")
    $base = 45
    if (-not (Test-MultishopNodoNeedsMysqlAtStartup -EnvMap $map)) {
        return $base
    }
    $attempts = 30
    $delay = 2.0
    if ($map["NODO_MYSQL_STARTUP_ATTEMPTS"]) {
        [void][int]::TryParse($map["NODO_MYSQL_STARTUP_ATTEMPTS"].Trim(), [ref]$attempts)
    }
    if ($map["NODO_MYSQL_STARTUP_DELAY_SECONDS"]) {
        [void][double]::TryParse($map["NODO_MYSQL_STARTUP_DELAY_SECONDS"].Trim(), [ref]$delay)
    }
    $mysqlWait = 60 * 2
    if ($map["MYSQL_WAIT_TRIES"]) {
        [void][int]::TryParse($map["MYSQL_WAIT_TRIES"].Trim(), [ref]$mysqlWait)
    }
    $mysqlSleep = 2.0
    if ($map["MYSQL_WAIT_SLEEP"]) {
        [void][double]::TryParse($map["MYSQL_WAIT_SLEEP"].Trim(), [ref]$mysqlSleep)
    }
    $computed = [int][Math]::Ceiling(($mysqlWait * $mysqlSleep) + ($attempts * $delay) + 15)
    if ($computed -lt $base) { return $base }
    if ($computed -gt 300) { return 300 }
    return $computed
}

function Get-MultishopNodoApiStartFailureHint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir
    )
    $port = Get-MultishopNodoApiPort -NodoDir $NodoDir
    $lines = @("Puerto esperado: $port (NODO_PORT en .env)")
    $logBasename = if (Get-Command Get-MultishopApiLogBasename -ErrorAction SilentlyContinue) {
        Get-MultishopApiLogBasename
    } else {
        'router-api'
    }
    $logDirs = @()
    if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) {
        $logDirs += Get-MultishopDeployRoot
    }
    foreach ($base in @($env:ProgramData, $env:LOCALAPPDATA)) {
        if (-not $base) { continue }
        $logDirs += Join-Path $base "Multishop"
        $logDirs += Join-Path $base "Multishop\router"
    }
    foreach ($logDir in ($logDirs | Select-Object -Unique)) {
        foreach ($name in @(
                "$logBasename-start.log",
                "$logBasename.err.log",
                "$logBasename.out.log",
                "nodo-api-start.log",
                "nodo-api.err.log",
                "nodo-api.out.log"
            )) {
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
