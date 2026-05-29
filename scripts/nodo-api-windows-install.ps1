# Tareas ONSTART para API + Huey (tienda en Program Files).
# Ejecutar PowerShell COMO ADMINISTRADOR.
#
#   .\nodo-api-windows-install.ps1 -NodoDir "C:\Program Files\Multishop\nodo"
#   .\nodo-api-windows-install.ps1 -NodoDir "C:\Program Files\Multishop\nodo" -StartNow
#   .\nodo-api-windows-install.ps1 -Uninstall

param(
    [string]$NodoDir = "",
    [string]$TunnelName = "wg0",
    [switch]$Uninstall,
    [switch]$StartNow
)

$MultishopWindowsInstallVersion = "20260530.2"

$ErrorActionPreference = "Stop"

$OnStartTaskNames = @(
    "Multishop-Nodo-API",
    "Multishop-Nodo-Huey"
)

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-AdminForInstall {
    if (Test-IsAdmin) { return }
    Write-Host ""
    Write-Host "ERROR: ejecute PowerShell COMO ADMINISTRADOR." -ForegroundColor Red
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
    $p = (Resolve-Path -LiteralPath $InputPath).Path.TrimEnd('\')
    for ($i = 0; $i -lt 6; $i++) {
        if (Test-NodoProjectRoot -Path $p) { return $p }
        if ((Split-Path $p -Leaf) -eq "scripts") {
            $p = (Split-Path $p -Parent).TrimEnd('\')
            continue
        }
        $parent = Split-Path $p -Parent
        if (-not $parent -or $parent -eq $p) { break }
        $p = $parent.TrimEnd('\')
    }
    throw "No se encontro la raiz del nodo (main.py). Use -NodoDir con la carpeta que contiene main.py"
}

$TaskNameOnStart = "Multishop-Nodo-API"
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
$TunnelName = ($TunnelName -replace '\s', '').Trim()
if (-not $TunnelName) { $TunnelName = "wg0" }

if (Test-Path -LiteralPath $SourceEnvHelper) {
    . $SourceEnvHelper
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

function Test-NodoApiTaskExists {
    param([string]$Name)
    if (Get-Command Test-MultishopScheduledTaskExists -ErrorAction SilentlyContinue) {
        return (Test-MultishopScheduledTaskExists -Name $Name)
    }
    foreach ($tn in @($Name, "\$Name")) {
        if (Invoke-SchTasksQuiet @("/Query", "/TN", $tn) -eq 0) { return $true }
    }
    return $false
}

function Remove-NodoApiTaskNamed {
    param([string]$Name)
    if (Get-Command Remove-MultishopScheduledTaskNamed -ErrorAction SilentlyContinue) {
        return (Remove-MultishopScheduledTaskNamed -Name $Name)
    }
    if (-not (Test-NodoApiTaskExists -Name $Name)) { return $false }
    foreach ($tn in @($Name, "\$Name")) {
        if (Invoke-SchTasksQuiet @("/Query", "/TN", $tn) -ne 0) { continue }
        Invoke-SchTasksQuiet @("/End", "/TN", $tn) | Out-Null
        if (Invoke-SchTasksQuiet @("/Delete", "/TN", $tn, "/F") -eq 0) { return $true }
    }
    return $false
}

function Remove-AllMultishopAutostartTasks {
    if (Get-Command Remove-MultishopNodoScheduledTasks -ErrorAction SilentlyContinue) {
        Remove-MultishopNodoScheduledTasks -Quiet | Out-Null
    } else {
        foreach ($name in $OnStartTaskNames) {
            Remove-NodoApiTaskNamed -Name $name | Out-Null
        }
    }
}

function Remove-NodoHueyAutostart {
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey" | Out-Null
    $hueyDeployed = Join-Path $DeployDir "start-nodo-huey.ps1"
    $hueyVbs = Join-Path $DeployDir "start-nodo-huey.vbs"
    if (Test-Path $hueyDeployed) { Remove-Item $hueyDeployed -Force }
    if (Test-Path $hueyVbs) { Remove-Item $hueyVbs -Force }
}

function Get-WindowsProgramFilesRoots {
    $roots = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($name in @('ProgramW6432', 'ProgramFiles')) {
        $val = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ($val) { [void]$roots.Add($val.TrimEnd('\')) }
    }
    $x86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)', 'Process')
    if ($x86) { [void]$roots.Add($x86.TrimEnd('\')) }
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
    if ($norm -match '(?i)^[A-Z]:\\Program Files\\') {
        return $true
    }
    return $false
}

function Copy-ItemIfDifferent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        return $false
    }
    $src = (Resolve-Path -LiteralPath $Source).Path
    $destParent = Split-Path -Parent $Destination
    if ($destParent -and -not (Test-Path -LiteralPath $destParent)) {
        New-Item -ItemType Directory -Path $destParent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $Destination) {
        $dst = (Resolve-Path -LiteralPath $Destination).Path
        if ($src -ieq $dst) {
            return $false
        }
    }
    Copy-Item -LiteralPath $src -Destination $Destination -Force
    return $true
}

function Deploy-NodoApiLauncher {
    Ensure-MultishopDeployDir -Path $DeployDir
    Set-Content -LiteralPath $DirFile -Value $NodoDir -Encoding ASCII -NoNewline -Force
    Set-Content -LiteralPath $TunnelFile -Value $TunnelName -Encoding ASCII -NoNewline -Force
    Copy-ItemIfDifferent -Source $SourceScript -Destination $DeployedScript | Out-Null
    if (Test-Path -LiteralPath $SourceEnvHelper) {
        Copy-ItemIfDifferent -Source $SourceEnvHelper -Destination $DeployedEnvHelper | Out-Null
    }
    $hueySource = Join-Path $PSScriptRoot "start-nodo-huey.ps1"
    if (Test-Path -LiteralPath $hueySource) {
        Copy-ItemIfDifferent -Source $hueySource -Destination (Join-Path $DeployDir "start-nodo-huey.ps1") | Out-Null
    }
    $nodoScriptsDir = Join-Path $NodoDir "scripts"
    if (Test-Path -LiteralPath $nodoScriptsDir) {
        Copy-ItemIfDifferent -Source $SourceScript -Destination (Join-Path $nodoScriptsDir "start-nodo-api.ps1") | Out-Null
        if (Test-Path -LiteralPath $SourceEnvHelper) {
            Copy-ItemIfDifferent -Source $SourceEnvHelper -Destination (Join-Path $nodoScriptsDir "nodo-env.ps1") | Out-Null
        }
        if (Test-Path -LiteralPath $hueySource) {
            Copy-ItemIfDifferent -Source $hueySource -Destination (Join-Path $nodoScriptsDir "start-nodo-huey.ps1") | Out-Null
        }
        Copy-ItemIfDifferent -Source $PSCommandPath -Destination (Join-Path $nodoScriptsDir "nodo-api-windows-install.ps1") | Out-Null
    }
    $vbsLines = @(
        'Set sh = CreateObject("Wscript.Shell")'
        "sh.Run ""powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """"$DeployedScript"""""", 0, False"
    )
    Set-Content -Path $DeployedVbs -Value ($vbsLines -join "`r`n") -Encoding ASCII -Force
    Write-Host "NodoDir: $NodoDir"
    Write-Host "Launcher: $DeployedVbs"
}

function Install-NodoApiOnStartTask {
    if (-not (Test-NodoInProgramFiles -Path $NodoDir)) {
        Write-Warning "Autostart ONSTART omitido: el nodo no esta en Program Files."
        return $false
    }
    if (Get-Command Set-MultishopOnStartTasksEnabled -ErrorAction SilentlyContinue) {
        Set-MultishopOnStartTasksEnabled -Enabled $false
    }
    $trCmd = 'wscript.exe //nologo "' + $DeployedVbs + '"'
    Remove-NodoApiTaskNamed -Name $TaskNameOnStart | Out-Null
    $output = & schtasks.exe @(
        "/Create", "/TN", $TaskNameOnStart, "/SC", "ONSTART",
        "/TR", $trCmd, "/RU", "SYSTEM", "/RL", "HIGHEST", "/DELAY", "0001:30", "/F"
    ) 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "schtasks ONSTART fallo: $output"
        return $false
    }
    Write-Host "Tarea $TaskNameOnStart registrada (ONSTART, delay 1:30)."
    return $true
}

function Install-NodoHueyAutostart {
    if (-not (Test-NodoInProgramFiles -Path $NodoDir)) {
        return
    }
    if (Get-Command Set-MultishopOnStartTasksEnabled -ErrorAction SilentlyContinue) {
        Set-MultishopOnStartTasksEnabled -Enabled $false
    }
    $hueyScript = Join-Path $PSScriptRoot "start-nodo-huey.ps1"
    if (-not (Test-Path -LiteralPath $hueyScript)) {
        Write-Warning "Missing $hueyScript; Huey ONSTART no se registrara."
        return
    }
    Copy-Item $hueyScript (Join-Path $DeployDir "start-nodo-huey.ps1") -Force
    $hueyVbs = Join-Path $DeployDir "start-nodo-huey.vbs"
    $vbsHuey = @(
        'Set sh = CreateObject("Wscript.Shell")'
        "sh.Run ""powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """"$($DeployDir)\start-nodo-huey.ps1"""""", 0, False"
    )
    Set-Content -Path $hueyVbs -Value ($vbsHuey -join "`r`n") -Encoding ASCII -Force
    $hueyTr = 'wscript.exe //nologo "' + $hueyVbs + '"'
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-Huey" | Out-Null
    $output = & schtasks.exe @(
        "/Create", "/TN", "Multishop-Nodo-Huey", "/SC", "ONSTART",
        "/TR", $hueyTr, "/RU", "SYSTEM", "/RL", "HIGHEST", "/DELAY", "0002:00", "/F"
    ) 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "schtasks Multishop-Nodo-Huey ONSTART failed: $output"
    } else {
        Write-Host "Tarea Multishop-Nodo-Huey registrada (ONSTART, delay 2:00)."
    }
}

function Start-NodoApiBackground {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DeployedScript
    Write-Host "API iniciada en segundo plano." -ForegroundColor Green
    Write-Host "Log: $DeployDir\nodo-api-start.log"
}

function Start-NodoHueyBackground {
    $hueyScript = Join-Path $DeployDir "start-nodo-huey.ps1"
    if (-not (Test-Path -LiteralPath $hueyScript)) {
        $hueyScript = Join-Path $PSScriptRoot "start-nodo-huey.ps1"
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hueyScript -NodoDir $NodoDir
    Write-Host "Huey consumer start requested (see $DeployDir\nodo-huey-start.log)." -ForegroundColor Green
}

function Show-MultishopScheduledTasks {
    Write-Host "Tareas ONSTART:"
    foreach ($name in $OnStartTaskNames) {
        if (Test-NodoApiTaskExists -Name $name) {
            Write-Host "  [OK] $name"
        } else {
            Write-Host "  [--] $name"
        }
    }
}

function Assert-MultishopSingleInstance {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDirPath,
        [bool]$ExpectHuey
    )
    if (-not (Get-Command Get-MultishopNodoProcessCounts -ErrorAction SilentlyContinue)) {
        return
    }
    Start-Sleep -Seconds 4
    $counts = Get-MultishopNodoProcessCounts -NodoDir $NodoDirPath
    $expectedApi = if ($StartNow) { 1 } else { 0 }
    $expectedHuey = if ($StartNow -and $ExpectHuey) { 1 } else { 0 }
    Write-Host "Procesos: API=$($counts.Api) Huey=$($counts.Huey) (esperado API=$expectedApi Huey=$expectedHuey)"
    if ($counts.Api -ne $expectedApi -or $counts.Huey -ne $expectedHuey) {
        throw "Multishop nodo: procesos incorrectos (API=$($counts.Api) Huey=$($counts.Huey))"
    }
    if ($StartNow -and -not (Test-MultishopNodoApiPortListening -NodoDir $NodoDirPath)) {
        throw "Multishop nodo: API no escucha en el puerto configurado."
    }
}

if ($Uninstall) {
    Assert-AdminForInstall
    if (Get-Command Stop-MultishopNodoProcesses -ErrorAction SilentlyContinue) {
        Stop-MultishopNodoProcesses -NodoDir $NodoDir
    }
    Remove-AllMultishopAutostartTasks
    Remove-NodoHueyAutostart
    if (Test-Path $DeployedVbs) { Remove-Item $DeployedVbs -Force }
    if (Test-Path $DeployedScript) { Remove-Item $DeployedScript -Force }
    if (Test-Path $DeployedEnvHelper) { Remove-Item $DeployedEnvHelper -Force }
    if (Test-Path $DirFile) { Remove-Item $DirFile -Force }
    if (Test-Path $TunnelFile) { Remove-Item $TunnelFile -Force }
    Write-Host "Autostart eliminado."
    exit 0
}

Assert-AdminForInstall

Write-Host "nodo-api-windows-install version: $MultishopWindowsInstallVersion"

if (-not (Test-NodoInProgramFiles -Path $NodoDir)) {
    Write-Warning "El nodo no esta en Program Files. Autostart ONSTART no se registrara."
}

Deploy-NodoApiLauncher

$enableHuey = $false
$envPath = Join-Path $NodoDir ".env"
if (Test-Path -LiteralPath $envPath) {
    $envText = Get-Content -LiteralPath $envPath -Raw
    if ($envText -match '(?m)^\s*HUEY_ENABLED\s*=\s*true\s*$') {
        $enableHuey = $true
    }
}

if ($StartNow) {
    if (Get-Command Invoke-PrepareMultishopStartNow -ErrorAction SilentlyContinue) {
        Invoke-PrepareMultishopStartNow -NodoDirPath $NodoDir
    }
    Start-NodoApiBackground
    if ($enableHuey) { Start-NodoHueyBackground }
    Assert-MultishopSingleInstance -NodoDirPath $NodoDir -ExpectHuey:$enableHuey
}

$null = Install-NodoApiOnStartTask
if ($enableHuey) {
    Install-NodoHueyAutostart
} else {
    Remove-NodoHueyAutostart
}

if (Get-Command Set-MultishopOnStartTasksEnabled -ErrorAction SilentlyContinue) {
    Set-MultishopOnStartTasksEnabled -Enabled $true
}

Show-MultishopScheduledTasks

Write-Host ""
Write-Host "Autostart ONSTART: Multishop-Nodo-API + Multishop-Nodo-Huey (si HUEY_ENABLED=true)."
Write-Host "Version: $MultishopWindowsInstallVersion"
exit 0
