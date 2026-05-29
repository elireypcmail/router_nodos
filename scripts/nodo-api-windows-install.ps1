# Tarea programada + carpeta Inicio para API nodo (arranque al iniciar sesion).
# Ejecutar PowerShell COMO ADMINISTRADOR.
#
#   .\nodo-api-windows-install.ps1 -NodoDir "C:\ruta\nodo\nodo"
#   .\nodo-api-windows-install.ps1 -NodoDir "C:\ruta\nodo\nodo" -TunnelName "wg0" -StartNow
#   .\nodo-api-windows-install.ps1 -Uninstall

param(
    [string]$NodoDir = "",
    [string]$TunnelName = "wg0",

    [switch]$Uninstall,

    [switch]$StartNow,

    [int]$LogonDelaySeconds = 45
)

$MultishopWindowsInstallVersion = "20260528.3"

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-AdminForInstall {
    if (Test-IsAdmin) { return }
    Write-Host ""
    Write-Host "ERROR: ejecute PowerShell COMO ADMINISTRADOR." -ForegroundColor Red
    Write-Host "  Clic derecho en PowerShell -> Ejecutar como administrador"
    Write-Host "  cd `"$PSScriptRoot`""
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\nodo-api-windows-install.ps1 -NodoDir `"$NodoDir`" -TunnelName `"$TunnelName`""
    Write-Host ""
    Write-Host "O doble clic en nodo-api-windows-install.cmd (Ejecutar como administrador)."
    exit 1
}

function Ensure-MultishopDeployDir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
    $inherit = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit,ObjectInherit"
    $propagate = [System.Security.AccessControl.PropagationFlags]::None
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($false, $true)
    foreach ($entry in @(
            @{ Sid = "S-1-5-18"; Rights = "FullControl" },
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
    Set-Acl -LiteralPath $Path -AclObject $acl
    & icacls.exe $Path /grant "*S-1-5-18:(OI)(CI)F" /T /C 2>$null | Out-Null
    & icacls.exe $Path /grant "*S-1-5-32-544:(OI)(CI)F" /T /C 2>$null | Out-Null
    & icacls.exe $Path /grant "*S-1-5-32-545:(OI)(CI)M" /T /C 2>$null | Out-Null
}

function Test-NodoProjectRoot {
    param([string]$Path)
    return (Test-Path -LiteralPath (Join-Path $Path "main.py"))
}

function Resolve-NodoProjectDir {
    param([string]$InputPath = "")
    if (-not $InputPath) {
        if (Test-Path (Join-Path $env:ProgramData "Multishop\nodo-dir.txt")) {
            $InputPath = (Get-Content (Join-Path $env:ProgramData "Multishop\nodo-dir.txt") -Raw).Trim()
        } else {
            $InputPath = $PSScriptRoot
        }
    }
    if (-not (Test-Path -LiteralPath $InputPath)) {
        throw "Ruta no existe: $InputPath"
    }
    $p = (Resolve-Path -LiteralPath $InputPath).Path.TrimEnd('\\')
    for ($i = 0; $i -lt 6; $i++) {
        if (Test-NodoProjectRoot -Path $p) {
            return $p
        }
        if ((Split-Path $p -Leaf) -eq "scripts") {
            $p = (Split-Path $p -Parent).TrimEnd('\\')
            continue
        }
        $parent = Split-Path $p -Parent
        if (-not $parent -or $parent -eq $p) {
            break
        }
        $p = $parent.TrimEnd('\\')
    }
    throw "No se encontro la raiz del nodo (main.py). Use -NodoDir con la carpeta que contiene main.py"
}

$TaskName = "Multishop-Nodo-API-Logon"
$TaskNameOnStart = "Multishop-Nodo-API"
$StartupVbsName = "Multishop-Nodo-API.vbs"
$DeployDir = Join-Path $env:ProgramData "Multishop"
$DirFile = Join-Path $DeployDir "nodo-dir.txt"
$TunnelFile = Join-Path $DeployDir "tunnel-name.txt"
$SourceScript = Join-Path $PSScriptRoot "start-nodo-api.ps1"
$SourceEnvHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
$DeployedScript = Join-Path $DeployDir "start-nodo-api.ps1"
$DeployedEnvHelper = Join-Path $DeployDir "nodo-env.ps1"
$DeployedVbs = Join-Path $DeployDir "start-nodo-api.vbs"

if (-not $Uninstall) {
    if (-not (Test-Path $SourceScript)) {
        Write-Error "No se encontro $SourceScript"
    }
}

$NodoDir = if ($Uninstall -and $NodoDir) {
    $NodoDir.TrimEnd('\')
} else {
    Resolve-NodoProjectDir -InputPath $NodoDir
}
$TunnelName = ($TunnelName -replace '\\s', '').Trim()
if (-not $TunnelName) { $TunnelName = "wg0" }

if (Test-Path -LiteralPath $SourceEnvHelper) {
    . $SourceEnvHelper
}

function Test-NodoApiTaskExists {
    param([string]$Name)
    if (Get-Command Test-MultishopScheduledTaskExists -ErrorAction SilentlyContinue) {
        return (Test-MultishopScheduledTaskExists -Name $Name)
    }
    foreach ($tn in @($Name, "\$Name")) {
        if (Invoke-SchTasksQuiet @("/Query", "/TN", $tn) -eq 0) {
            return $true
        }
    }
    return $false
}

function Remove-NodoApiTaskNamed {
    param([string]$Name)
    if (Get-Command Remove-MultishopScheduledTaskNamed -ErrorAction SilentlyContinue) {
        $ok = Remove-MultishopScheduledTaskNamed -Name $Name
        if (-not $ok -and (Test-MultishopScheduledTaskExists -Name $Name)) {
            Write-Warning "No se pudo eliminar tarea $Name."
        }
        return $ok
    }
    if (-not (Test-NodoApiTaskExists -Name $Name)) { return $false }
    return (Invoke-SchTasksDelete -Name $Name)
}

function Format-SchTasksDelay {
    param([int]$Seconds)
    $mins = [int][math]::Floor($Seconds / 60)
    $secs = [int]($Seconds % 60)
    return $mins.ToString("0000") + ":" + $secs.ToString("00")
}

function Invoke-SchTasksQuiet {
    param([string[]]$ArgumentList)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $null = schtasks.exe @ArgumentList 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
}

function Invoke-SchTasksDelete {
    param([string]$Name)
    if (-not $Name) { return $false }
    $candidates = @($Name)
    if (-not $Name.StartsWith("\")) {
        $candidates += "\$Name"
    }
    foreach ($tn in $candidates) {
        if (Invoke-SchTasksQuiet @("/Query", "/TN", $tn) -ne 0) { continue }
        $code = Invoke-SchTasksQuiet @("/Delete", "/TN", $tn, "/F")
        if ($code -eq 0) {
            return $true
        }
    }
    return $false
}

function Remove-NodoApiLogonTask {
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-API-Logon"
}

function Remove-NodoApiTasksLegacy {
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-API"
    Remove-NodoApiLogonTask
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey" | Out-Null
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey-Logon" | Out-Null
}

function Remove-NodoHueyAutostart {
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey" | Out-Null
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey-Logon" | Out-Null
    $hueyDeployed = Join-Path $DeployDir "start-nodo-huey.ps1"
    $hueyVbs = Join-Path $DeployDir "start-nodo-huey.vbs"
    if (Test-Path $hueyDeployed) { Remove-Item $hueyDeployed -Force }
    if (Test-Path $hueyVbs) { Remove-Item $hueyVbs -Force }
}

function Install-NodoHueyAutostart {
    $hueyScript = Join-Path $PSScriptRoot "start-nodo-huey.ps1"
    $hueyDeployed = Join-Path $DeployDir "start-nodo-huey.ps1"
    if (-not (Test-Path -LiteralPath $hueyScript)) {
        Write-Warning "Missing $hueyScript; Huey consumer task will not be registered."
        return
    }
    Copy-Item $hueyScript $hueyDeployed -Force
    $hueyVbs = Join-Path $DeployDir "start-nodo-huey.vbs"
    $vbsHuey = @(
        'Set sh = CreateObject("Wscript.Shell")'
        "sh.Run ""powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """"$hueyDeployed"""""", 0, False"
    )
    Set-Content -Path $hueyVbs -Value ($vbsHuey -join "`r`n") -Encoding ASCII -Force
    $hueyTr = 'wscript.exe //nologo "' + $hueyVbs + '"'

    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey" | Out-Null
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey-Logon" | Out-Null

    if (Test-NodoInProgramFiles -Path $NodoDir) {
        $onStartArgs = @(
            "/Create", "/TN", "Multishop-Nodo-Huey", "/SC", "ONSTART",
            "/TR", $hueyTr, "/RU", "SYSTEM", "/RL", "HIGHEST", "/DELAY", "0002:00", "/F"
        )
        $onStartOut = & schtasks.exe @onStartArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "schtasks Multishop-Nodo-Huey ONSTART failed: $onStartOut"
        } else {
            Write-Host "Task Multishop-Nodo-Huey registered (ONSTART SYSTEM only, ~2 min delay)."
        }
        return
    }

    $runUser = "$env:USERDOMAIN\$env:USERNAME"
    $logonDelay = Format-SchTasksDelay -Seconds 60
    $onLogonArgs = @(
        "/Create", "/TN", "Multishop-Nodo-Huey-Logon", "/SC", "ONLOGON",
        "/TR", $hueyTr, "/RU", $runUser, "/RL", "HIGHEST", "/DELAY", $logonDelay, "/IT", "/F"
    )
    $onLogonOut = & schtasks.exe @onLogonArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "schtasks Multishop-Nodo-Huey-Logon failed: $onLogonOut"
    } else {
        Write-Host "Task Multishop-Nodo-Huey-Logon registered (ONLOGON only, delay $logonDelay)."
    }
}

function Start-NodoHueyBackground {
    $hueyScript = Join-Path $DeployDir "start-nodo-huey.ps1"
    if (-not (Test-Path -LiteralPath $hueyScript)) {
        $hueyScript = Join-Path $PSScriptRoot "start-nodo-huey.ps1"
    }
    if (-not (Test-Path -LiteralPath $hueyScript)) {
        Write-Warning "Huey launcher not found; skipping immediate start."
        return
    }
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hueyScript -NodoDir $NodoDir
        Write-Host "Huey consumer start requested (see $DeployDir\nodo-huey-start.log)." -ForegroundColor Green
    } catch {
        Write-Host "Could not start Huey: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "See $DeployDir\nodo-huey-start.log and nodo-huey.err.log"
        throw
    }
}

function Get-StartupFolderVbs {
    $startup = [Environment]::GetFolderPath("Startup")
    return Join-Path $startup $StartupVbsName
}

function Install-NodoApiStartupFolder {
    $dest = Get-StartupFolderVbs
    Copy-Item $DeployedVbs $dest -Force
    Write-Host "Carpeta Inicio (al iniciar sesion): $dest"
}

function Remove-NodoApiStartupFolder {
    $dest = Get-StartupFolderVbs
    if (Test-Path $dest) {
        Remove-Item $dest -Force
    }
}

function Deploy-NodoApiLauncher {
    Ensure-MultishopDeployDir -Path $DeployDir
    Set-Content -LiteralPath $DirFile -Value $NodoDir -Encoding ASCII -NoNewline -Force
    Set-Content -LiteralPath $TunnelFile -Value $TunnelName -Encoding ASCII -NoNewline -Force
    Copy-Item $SourceScript $DeployedScript -Force
    if (Test-Path -LiteralPath $SourceEnvHelper) {
        Copy-Item $SourceEnvHelper $DeployedEnvHelper -Force
    }
    $vbsLines = @(
        'Set sh = CreateObject("Wscript.Shell")'
        "sh.Run ""powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """"$DeployedScript"""""", 0, False"
    )
    Set-Content -Path $DeployedVbs -Value ($vbsLines -join "`r`n") -Encoding ASCII -Force
    if (-not (Test-Path $DeployedVbs)) {
        throw "No se pudo crear $DeployedVbs"
    }
    Write-Host "NodoDir: $NodoDir"
    Write-Host "Tunel VPN: $TunnelName"
    Write-Host "Launcher: $DeployedVbs"
}

function Get-WindowsProgramFilesRoots {
    $roots = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($name in @('ProgramW6432', 'ProgramFiles')) {
        $val = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ($val) {
            [void]$roots.Add($val.TrimEnd('\'))
        }
    }
    $x86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)', 'Process')
    if ($x86) {
        [void]$roots.Add($x86.TrimEnd('\'))
    }
    return @($roots)
}

function Test-NodoInProgramFiles {
    param([string]$Path)
    $norm = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
    foreach ($root in Get-WindowsProgramFilesRoots) {
        if ($norm.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    # WOW64: 32-bit PowerShell redirige ProgramFiles a (x86); ruta real suele ser C:\Program Files\...
    if ($norm -match '(?i)^[A-Z]:\\Program Files\\') {
        return $true
    }
    return $false
}

function Install-NodoApiOnStartTask {
    if (-not (Test-NodoInProgramFiles -Path $NodoDir)) {
        Write-Host "ONSTART omitido (nodo fuera de Program Files; use ONLOGON)."
        return $false
    }
    if (-not (Test-Path $DeployedVbs)) {
        throw "Falta launcher $DeployedVbs"
    }
    $trCmd = 'wscript.exe //nologo "' + $DeployedVbs + '"'
    if ($trCmd.Length -gt 261) {
        throw "Comando /TR demasiado largo ($($trCmd.Length) chars, max 261)"
    }
    Remove-NodoApiTaskNamed -Name $TaskNameOnStart
    $schArgs = @(
        "/Create",
        "/TN", $TaskNameOnStart,
        "/SC", "ONSTART",
        "/TR", $trCmd,
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/DELAY", "0001:30",
        "/F"
    )
    $output = & schtasks.exe @schArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "schtasks ONSTART fallo: $output"
        return $false
    }
    Write-Host "Tarea $TaskNameOnStart registrada (ONSTART SYSTEM, retraso 1:30)."
    return $true
}

function Install-NodoApiScheduledTask {
    if (-not (Test-Path $DeployedVbs)) {
        throw "Falta launcher $DeployedVbs"
    }

    Remove-NodoApiLogonTask

    if (Test-NodoInProgramFiles -Path $NodoDir) {
        Write-Host "ONLOGON omitido (Program Files: solo tarea $TaskNameOnStart)."
        return
    }

    $trCmd = 'wscript.exe //nologo "' + $DeployedVbs + '"'
    if ($trCmd.Length -gt 261) {
        throw "Comando /TR demasiado largo ($($trCmd.Length) chars, max 261)"
    }

    $runUser = "$env:USERDOMAIN\$env:USERNAME"
    $delay = Format-SchTasksDelay -Seconds $LogonDelaySeconds
    $schArgs = @(
        "/Create",
        "/TN", $TaskName,
        "/SC", "ONLOGON",
        "/TR", $trCmd,
        "/RU", $runUser,
        "/RL", "HIGHEST",
        "/DELAY", $delay,
        "/IT",
        "/F"
    )
    $output = & schtasks.exe @schArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks ONLOGON fallo: $output"
    }
    Write-Host "Tarea $TaskName registrada (ONLOGON, retraso $delay, usuario $runUser)."
}

function Start-NodoApiBackground {
    if (-not (Test-Path -LiteralPath $DeployedScript)) {
        throw "Falta launcher $DeployedScript"
    }
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DeployedScript
        Write-Host "API iniciada en segundo plano." -ForegroundColor Green
        Write-Host "Log arranque: $DeployDir\nodo-api-start.log"
        Write-Host "Salida API:  $DeployDir\nodo-api.out.log"
        Write-Host "Errores:     $DeployDir\nodo-api.err.log"
    } catch {
        Write-Host "No se pudo iniciar la API: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Revise $DeployDir\nodo-api.err.log"
        throw
    }
}

function Invoke-SanitizeMultishopAutostart {
    param(
        [string]$NodoDirPath,
        [switch]$StopProcesses,
        [ValidateSet('All', 'LogonOnly')]
        [string]$TaskScope = 'All'
    )
    Write-Host "Sanitizando autostart Multishop (version $MultishopWindowsInstallVersion, scope=$TaskScope) ..."
    Remove-NodoApiStartupFolder
    if (Get-Command Remove-MultishopNodoScheduledTasks -ErrorAction SilentlyContinue) {
        Remove-MultishopNodoScheduledTasks -Scope $(if ($TaskScope -eq 'LogonOnly') { 'LogonOnly' } else { 'All' })
    } else {
        foreach ($name in @(
                "Multishop-Nodo-API",
                "Multishop-Nodo-API-Logon",
                "Multishop-Nodo-Huey",
                "Multishop-Nodo-Huey-Logon"
            )) {
            if ($TaskScope -eq 'LogonOnly' -and $name -notmatch '-Logon$') { continue }
            Remove-NodoApiTaskNamed -Name $name | Out-Null
        }
    }
    if ($StopProcesses) {
        $envHelper = $SourceEnvHelper
        if (Test-Path -LiteralPath $DeployedEnvHelper) {
            $envHelper = $DeployedEnvHelper
        }
        if (Test-Path -LiteralPath $envHelper) {
            . $envHelper
            if (Get-Command Stop-MultishopNodoProcesses -ErrorAction SilentlyContinue) {
                Stop-MultishopNodoProcesses -NodoDir $NodoDirPath
            }
        }
    }
}

function Show-MultishopScheduledTasks {
    Write-Host "Tareas Multishop registradas:"
    foreach ($name in @(
            "Multishop-Nodo-API",
            "Multishop-Nodo-API-Logon",
            "Multishop-Nodo-Huey",
            "Multishop-Nodo-Huey-Logon"
        )) {
        if (Test-NodoApiTaskExists -Name $name) {
            Write-Host "  [OK] $name"
        }
    }
    $startup = Get-StartupFolderVbs
    if (Test-Path -LiteralPath $startup) {
        Write-Warning "  [DUPLICADO] Carpeta Inicio: $startup"
    }
}

function Assert-NoMultishopLogonTasks {
    foreach ($name in @("Multishop-Nodo-API-Logon", "Multishop-Nodo-Huey-Logon")) {
        if (Get-Command Remove-MultishopScheduledTaskNamed -ErrorAction SilentlyContinue) {
            Remove-MultishopScheduledTaskNamed -Name $name | Out-Null
        } else {
            Remove-NodoApiTaskNamed -Name $name | Out-Null
        }
    }
    $bad = @()
    foreach ($name in @("Multishop-Nodo-API-Logon", "Multishop-Nodo-Huey-Logon")) {
        if (Test-NodoApiTaskExists -Name $name) {
            $bad += $name
        }
    }
    if ($bad.Count -eq 0) {
        return
    }
    Write-Host ""
    Write-Host "ADVERTENCIA: tareas ONLOGON residuales: $($bad -join ', ')" -ForegroundColor Yellow
    Write-Host "  En Program Files solo deben existir Multishop-Nodo-API y Multishop-Nodo-Huey (ONSTART)." -ForegroundColor Yellow
    Write-Host "  Borre manualmente (admin):" -ForegroundColor Yellow
    foreach ($name in $bad) {
        Write-Host "    Unregister-ScheduledTask -TaskName '$name' -Confirm:`$false" -ForegroundColor Yellow
    }
}

function Assert-MultishopSingleInstance {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDirPath,
        [bool]$ExpectHuey
    )
    if (-not (Test-Path -LiteralPath $DeployedEnvHelper)) {
        return
    }
    . $DeployedEnvHelper
    if (-not (Get-Command Get-MultishopNodoProcessCounts -ErrorAction SilentlyContinue)) {
        return
    }
    Start-Sleep -Seconds 2
    $counts = Get-MultishopNodoProcessCounts -NodoDir $NodoDirPath
    $expectedApi = if ($StartNow) { 1 } else { 0 }
    $expectedHuey = if ($StartNow -and $ExpectHuey) { 1 } else { 0 }
    Write-Host "Procesos Multishop: API=$($counts.Api) Huey=$($counts.Huey) (esperado API=$expectedApi Huey=$expectedHuey)"
    if ($counts.Api -gt 1 -or ($ExpectHuey -and $counts.Huey -gt 1)) {
        Write-Host ""
        Write-Host "ERROR: procesos duplicados. Instalador viejo o tareas Logon/Inicio activas." -ForegroundColor Red
        Write-Host "  Version requerida del instalador: $MultishopWindowsInstallVersion" -ForegroundColor Yellow
        Write-Host "  Copie scripts desde el repo actualizado antes de reinstalar." -ForegroundColor Yellow
        Show-MultishopScheduledTasks
        throw "Multishop nodo: duplicate python processes (API=$($counts.Api) Huey=$($counts.Huey))"
    }
}

if ($Uninstall) {
    Assert-AdminForInstall
    Remove-NodoApiTasksLegacy
    Remove-NodoHueyAutostart
    Remove-NodoApiStartupFolder
    if (Test-Path $DeployedVbs) { Remove-Item $DeployedVbs -Force }
    if (Test-Path $DeployedScript) { Remove-Item $DeployedScript -Force }
    if (Test-Path $DeployedEnvHelper) { Remove-Item $DeployedEnvHelper -Force }
    if (Test-Path $DirFile) { Remove-Item $DirFile -Force }
    if (Test-Path $TunnelFile) { Remove-Item $TunnelFile -Force }
    Write-Host "Autostart API y Huey eliminados (tareas + carpeta Inicio)."
    exit 0
}

Assert-AdminForInstall

Write-Host "nodo-api-windows-install version: $MultishopWindowsInstallVersion"

$inProgramFiles = Test-NodoInProgramFiles -Path $NodoDir
Write-Host "Modo autostart: $(if ($inProgramFiles) { 'Program Files -> ONSTART (SYSTEM)' } else { 'fuera de Program Files -> ONLOGON' })"

Invoke-SanitizeMultishopAutostart -NodoDirPath $NodoDir -StopProcesses
Deploy-NodoApiLauncher
$null = Install-NodoApiOnStartTask
Install-NodoApiScheduledTask

$envPath = Join-Path $NodoDir ".env"
$enableHuey = $false
if (Test-Path -LiteralPath $envPath) {
    $envText = Get-Content -LiteralPath $envPath -Raw
    if ($envText -match '(?m)^\s*HUEY_ENABLED\s*=\s*true\s*$') {
        $enableHuey = $true
    }
}
if ($enableHuey) {
    Install-NodoHueyAutostart
} else {
    Remove-NodoHueyAutostart
}

if ($StartNow) {
    Invoke-SanitizeMultishopAutostart -NodoDirPath $NodoDir -StopProcesses -TaskScope LogonOnly
    Start-NodoApiBackground
    if ($enableHuey) {
        Start-NodoHueyBackground
    }
}

if ($inProgramFiles) {
    Assert-NoMultishopLogonTasks
}
Show-MultishopScheduledTasks
Assert-MultishopSingleInstance -NodoDirPath $NodoDir -ExpectHuey:$enableHuey

Write-Host ""
Write-Host "Autostart (Program Files): 1 tarea ONSTART por servicio (API + Huey si HUEY_ENABLED=true)."
Write-Host "Sin carpeta Inicio ni ONLOGON duplicado."
Write-Host "Instalador version: $MultishopWindowsInstallVersion"
Write-Host "Revise: Get-Content $DeployDir\nodo-api-start.log -Tail 20"
Write-Host ""
Write-Host "Probar ahora:"
Write-Host "  wscript.exe //nologo `"$DeployedVbs`""
Write-Host "  schtasks /Run /TN `"$TaskNameOnStart`""
Write-Host "  schtasks /Run /TN `"Multishop-Nodo-Huey`"   # si HUEY_ENABLED=true"
$healthPort = 8443
if (Test-Path -LiteralPath $SourceEnvHelper) {
    . $SourceEnvHelper
    $healthPort = Get-MultishopNodoApiPort -NodoDir $NodoDir
}
Write-Host "  curl http://127.0.0.1:$healthPort/api/health -H `"Authorization: Bearer <TOKEN>`""
Write-Host ""
Write-Host "Desinstalar:"
Write-Host "  .\nodo-api-windows-install.ps1 -Uninstall"
