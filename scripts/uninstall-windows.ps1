# Desinstalador completo Multishop nodo (Windows).
# Quita API en segundo plano, tareas programadas, tunel WireGuard wg0 y archivos en Program Files.
#
# Ejecutar PowerShell COMO ADMINISTRADOR (o uninstall-windows.cmd).
#
#   .\uninstall-windows.ps1
#   .\uninstall-windows.ps1 -NodoDir "C:\Program Files\Multishop\nodo"
#   .\uninstall-windows.ps1 -Force
#   .\uninstall-windows.ps1 -KeepVpn -KeepLogs
#   .\uninstall-windows.ps1 -KeepProgramFiles   # solo quitar tareas/servicios, conservar carpeta

param(
    [string]$NodoDir = "",

    [string]$TunnelName = "wg0",

    [string]$ScriptsDir = "",

    [switch]$Force,

    [switch]$KeepVpn,

    [switch]$KeepProgramFiles,

    [switch]$KeepLogs
)

$ErrorActionPreference = "Stop"

$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (Test-Path -LiteralPath $envHelper) {
    . $envHelper
}

$WireGuardExe = Join-Path ${env:ProgramFiles} "WireGuard\wireguard.exe"
$DefaultInstallRoot = Join-Path ${env:ProgramFiles} "Multishop\nodo"
$ProgramDataDir = Join-Path $env:ProgramData "Multishop"
$LocalAppDataDir = Join-Path $env:LOCALAPPDATA "Multishop"

$ApiTaskNames = @(
    "Multishop-Nodo-API",
    "Multishop-Nodo-API-Logon",
    "Multishop-Nodo-Huey"
)
$WgResumeTaskNames = @(
    "Multishop-WG-Resume",
    "Multishop-WG-Resume-Hibernate"
)
$StartupVbsName = "Multishop-Nodo-API.vbs"

if (-not $ScriptsDir) {
    $ScriptsDir = $PSScriptRoot
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Admin {
    if (Test-IsAdmin) { return }
    Write-Host ""
    Write-Host "ERROR: ejecute PowerShell COMO ADMINISTRADOR." -ForegroundColor Red
    Write-Host "  Clic derecho en uninstall-windows.cmd -> Ejecutar como administrador"
    exit 1
}

function Test-NodoProjectRoot {
    param([string]$Path)
    return (Test-Path -LiteralPath (Join-Path $Path "main.py"))
}

function Resolve-NodoInstallDir {
    param([string]$InputPath = "")
    $candidates = @()
    if ($InputPath) {
        $candidates += $InputPath
    }
    $dirFile = Join-Path $ProgramDataDir "nodo-dir.txt"
    if (Test-Path -LiteralPath $dirFile) {
        $candidates += (Get-Content -LiteralPath $dirFile -Raw).Trim()
    }
    $candidates += $DefaultInstallRoot
    $parentOfScripts = Split-Path $ScriptsDir -Parent
    if (Test-NodoProjectRoot -Path $parentOfScripts) {
        $candidates += (Resolve-Path -LiteralPath $parentOfScripts).Path.TrimEnd('\\')
    }

    foreach ($raw in $candidates) {
        if (-not $raw) { continue }
        if (-not (Test-Path -LiteralPath $raw)) { continue }
        $p = (Resolve-Path -LiteralPath $raw).Path.TrimEnd('\\')
        for ($i = 0; $i -lt 6; $i++) {
            if (Test-NodoProjectRoot -Path $p) {
                return $p
            }
            if ((Split-Path $p -Leaf) -eq "scripts") {
                $p = (Split-Path $p -Parent).TrimEnd('\\')
                continue
            }
            $parent = Split-Path $p -Parent
            if (-not $parent -or $parent -eq $p) { break }
            $p = $parent.TrimEnd('\\')
        }
    }

    if (Test-Path -LiteralPath $DefaultInstallRoot) {
        return (Resolve-Path -LiteralPath $DefaultInstallRoot).Path.TrimEnd('\\')
    }

    throw "No se encontro la instalacion del nodo (main.py). Use -NodoDir con la ruta correcta."
}

function Test-PathIsUnder {
    param(
        [string]$Child,
        [string]$Parent
    )
    if (-not $Child -or -not $Parent) { return $false }
    try {
        $c = (Resolve-Path -LiteralPath $Child -ErrorAction Stop).Path.TrimEnd('\\')
        $p = (Resolve-Path -LiteralPath $Parent -ErrorAction Stop).Path.TrimEnd('\\')
        return ($c -ieq $p) -or $c.StartsWith($p + '\\', [StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Invoke-RelaunchFromTempIfNeeded {
    param([string]$InstallRoot)
    if ($env:MULTISHOP_UNINSTALL_RELAUNCHED -eq "1") { return }
    if (-not (Test-PathIsUnder -Child $ScriptsDir -Parent $InstallRoot)) { return }

    Write-Host "El script corre desde la carpeta a borrar; se relanza desde TEMP ..." -ForegroundColor Yellow
    $tempScript = Join-Path $env:TEMP ("multishop-uninstall-" + (Get-Date -Format "yyyyMMddHHmmss") + ".ps1")
    Copy-Item -LiteralPath $PSCommandPath -Destination $tempScript -Force

    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $tempScript,
        "-NodoDir", $InstallRoot
    )
    if ($Force) { $argList += "-Force" }
    if ($KeepVpn) { $argList += "-KeepVpn" }
    if ($KeepProgramFiles) { $argList += "-KeepProgramFiles" }
    if ($KeepLogs) { $argList += "-KeepLogs" }
    $argList += "-ScriptsDir"
    $argList += $ScriptsDir
    if ($TunnelName -and $TunnelName -ne "wg0") {
        $argList += "-TunnelName"
        $argList += $TunnelName
    }

    $env:MULTISHOP_UNINSTALL_RELAUNCHED = "1"
    & powershell.exe @argList
    $code = $LASTEXITCODE
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    exit $code
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

function Remove-SchTaskNamed {
    param([string]$Name)
    if (-not $Name) { return }
    if (Invoke-SchTasksQuiet @("/Query", "/TN", $Name) -eq 0) {
        Write-Host "Eliminando tarea $Name ..."
        Invoke-SchTasksQuiet @("/Delete", "/TN", $Name, "/F") | Out-Null
    }
}

function Stop-NodoApiProcesses {
    param([string]$NodoDirPath)
    $envHelper = Join-Path $ScriptsDir "nodo-env.ps1"
    if (-not (Test-Path -LiteralPath $envHelper)) {
        $envHelper = Join-Path $ProgramDataDir "nodo-env.ps1"
    }
    if (Test-Path -LiteralPath $envHelper) {
        . $envHelper
        Stop-MultishopNodoProcesses -NodoDir $NodoDirPath
        return
    }
    Write-Warning "nodo-env.ps1 not found; skipping targeted process stop."
}

function Remove-NodoApiAutostart {
    param([string]$InstallRoot)
    $apiScript = Join-Path $ScriptsDir "nodo-api-windows-install.ps1"
    if (Test-Path -LiteralPath $apiScript) {
        Write-Host "--- Autostart API (nodo-api-windows-install.ps1) ---"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $apiScript -Uninstall -NodoDir $InstallRoot
    } else {
        Write-Warning "No se encontro nodo-api-windows-install.ps1; eliminando tareas manualmente."
        foreach ($name in $ApiTaskNames) {
            Remove-SchTaskNamed -Name $name
        }
        $startup = Join-Path ([Environment]::GetFolderPath("Startup")) $StartupVbsName
        if (Test-Path -LiteralPath $startup) {
            Remove-Item -LiteralPath $startup -Force
            Write-Host "Eliminado $startup"
        }
    }
}

function Remove-WgResumeTasks {
    param([string]$Tunnel)
    $wgScript = Join-Path $ScriptsDir "wg-resume-windows-install.ps1"
    if (Test-Path -LiteralPath $wgScript) {
        Write-Host "--- Tareas VPN resume/hibernacion ---"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wgScript -TunnelName $Tunnel -Uninstall
    } else {
        Write-Warning "No se encontro wg-resume-windows-install.ps1; eliminando tareas manualmente."
        foreach ($name in $WgResumeTaskNames) {
            Remove-SchTaskNamed -Name $name
        }
    }
}

function Get-WireGuardTunnelServices {
    return @(Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "WireGuardTunnel*" })
}

function Find-WireGuardTunnelService {
    param([string]$Name)
    if (-not $Name) { return $null }
    $expected = "WireGuardTunnel`$$Name"
    $svc = Get-Service -Name $expected -ErrorAction SilentlyContinue
    if ($svc) { return $svc }
    foreach ($candidate in (Get-WireGuardTunnelServices)) {
        $tunnel = $candidate.Name -replace "^WireGuardTunnel\$", ""
        if ($tunnel -ieq $Name) {
            return $candidate
        }
    }
    return $null
}

function Invoke-WgNative {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $output = & wg @ArgumentList 2>&1
        return @{ ExitCode = $LASTEXITCODE; Output = @($output) }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Test-WgTunnelInterfaceActive {
    param([string]$Name)
    if (-not $Name) { return $false }
    if (-not (Get-Command wg -ErrorAction SilentlyContinue)) { return $false }
    $result = Invoke-WgNative -ArgumentList @("show", $Name)
    return ($result.ExitCode -eq 0)
}

function Stop-WireGuardTrayApp {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    foreach ($procName in @("wireguard", "WireGuard")) {
        $procs = @(Get-Process -Name $procName -ErrorAction SilentlyContinue)
        if ($procs.Count -eq 0) { continue }
        Stop-Process -Name $procName -Force -ErrorAction SilentlyContinue
    }
    $ErrorActionPreference = $prev
    Start-Sleep -Seconds 2
}

function Remove-WireGuardGuiConfig {
    param([string]$Name)
    if (-not $Name) { return }
    $guiDir = Join-Path ${env:ProgramFiles} "WireGuard\Data\Configurations"
    if (-not (Test-Path -LiteralPath $guiDir)) { return }
    foreach ($suffix in @(".conf", ".conf.dpapi")) {
        $guiPath = Join-Path $guiDir "$Name$suffix"
        if (Test-Path -LiteralPath $guiPath) {
            Remove-Item -LiteralPath $guiPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Remove-WireGuardTunnelService {
    param([string]$Name)
    if (-not $Name) { return }
    if (-not (Test-Path -LiteralPath $WireGuardExe)) {
        Write-Warning "WireGuard no instalado; omitiendo tunel $Name."
        return
    }

    $serviceName = "WireGuardTunnel`$$Name"
    $svc = Find-WireGuardTunnelService -Name $Name
    if (-not $svc) {
        $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    }
    if ($svc -and $svc.Status -eq "Running") {
        Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    $out = & $WireGuardExe /uninstalltunnelservice $Name 2>&1
    Start-Sleep -Seconds 2

    $still = Find-WireGuardTunnelService -Name $Name
    if (-not $still) {
        $still = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    }
    if ($still) {
        sc.exe stop $still.Name 2>&1 | Out-Host
        Start-Sleep -Seconds 2
        sc.exe delete $still.Name 2>&1 | Out-Host
        Start-Sleep -Seconds 2
    }
}

function Get-WireGuardTunnelNamesToRemove {
    param([string]$PrimaryName)
    $names = @($PrimaryName, "w0g")
    $tunnelFile = Join-Path $ProgramDataDir "tunnel-name.txt"
    if (Test-Path -LiteralPath $tunnelFile) {
        $fromFile = (Get-Content -LiteralPath $tunnelFile -Raw).Trim()
        if ($fromFile) { $names += $fromFile }
    }
    foreach ($svc in (Get-WireGuardTunnelServices)) {
        $tunnel = $svc.Name -replace "^WireGuardTunnel\$", ""
        if ($tunnel -match '^(wg0|w0g)$') {
            $names += $tunnel
        }
    }
    return @($names | Where-Object { $_ } | Select-Object -Unique)
}

function Test-WireGuardVpnRemoved {
    param([string[]]$TunnelNames)
    foreach ($n in $TunnelNames) {
        if (Test-WgTunnelInterfaceActive -Name $n) {
            return $false
        }
    }
    return $true
}

function Remove-WireGuardVpn {
    param([string]$PrimaryName)
    if (-not (Test-Path -LiteralPath $WireGuardExe)) {
        Write-Warning "WireGuard no instalado; omitiendo tunel."
        return
    }

    $names = Get-WireGuardTunnelNamesToRemove -PrimaryName $PrimaryName

    Stop-WireGuardTrayApp

    foreach ($n in $names) {
        Remove-WireGuardTunnelService -Name $n
        Remove-WireGuardGuiConfig -Name $n
    }

    Start-Sleep -Seconds 2
    if (Test-WireGuardVpnRemoved -TunnelNames $names) {
        Write-Host "WireGuard: ninguna interfaz $($names -join ', ') activa." -ForegroundColor Green
        return
    }

    Write-Warning "La interfaz WireGuard sigue activa tras desinstalar el servicio."
}

function Remove-MultishopDataDirs {
    if ($KeepLogs) {
        Write-Host "Conservando logs (-KeepLogs)."
        $toRemove = @(
            (Join-Path $ProgramDataDir "start-nodo-api.ps1"),
            (Join-Path $ProgramDataDir "nodo-env.ps1"),
            (Join-Path $ProgramDataDir "start-nodo-api.vbs"),
            (Join-Path $ProgramDataDir "wg-resume.ps1"),
            (Join-Path $ProgramDataDir "wg-resume.cmd"),
            (Join-Path $ProgramDataDir "nodo-dir.txt"),
            (Join-Path $ProgramDataDir "tunnel-name.txt")
        )
        foreach ($f in $toRemove) {
            if (Test-Path -LiteralPath $f) {
                Remove-Item -LiteralPath $f -Force
            }
        }
        return
    }

    foreach ($dir in @($ProgramDataDir, $LocalAppDataDir)) {
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction Continue
    }
}

function Remove-NodoInstallTree {
    param([string]$InstallRoot)
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        return
    }
    try {
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction Stop
        Write-Host "Carpeta del nodo eliminada." -ForegroundColor Green
    } catch {
        Write-Warning "No se pudo borrar todo: $($_.Exception.Message)"
    }

    $multishopRoot = Split-Path $InstallRoot -Parent
    if ((Split-Path $multishopRoot -Leaf) -ieq "Multishop") {
        $left = Get-ChildItem -LiteralPath $multishopRoot -ErrorAction SilentlyContinue
        if (-not $left) {
            Remove-Item -LiteralPath $multishopRoot -Force -ErrorAction SilentlyContinue
        }
    }
}

function Show-UninstallPlan {
    param(
        [string]$InstallRoot,
        [string]$Tunnel
    )
    Write-Host ""
    Write-Host "=== Multishop - desinstalacion nodo (Windows) ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Se realizaran estas acciones:"
    Write-Host "  1. Detener API Python (puerto NODO_PORT en .env y venv del nodo)"
    Write-Host "  2. Quitar tareas: $($ApiTaskNames -join ', ')"
    Write-Host "  3. Quitar tareas: $($WgResumeTaskNames -join ', ')"
    Write-Host "  4. Quitar acceso directo en carpeta Inicio ($StartupVbsName)"
    if (-not $KeepVpn) {
        Write-Host "  5. Desinstalar tunel WireGuard: $Tunnel (+ w0g si existe)"
    } else {
        Write-Host "  5. Conservar tunel WireGuard (-KeepVpn)"
    }
    if (-not $KeepLogs) {
        Write-Host "  6. Borrar $ProgramDataDir y $LocalAppDataDir"
    } else {
        Write-Host "  6. Conservar logs; quitar solo launchers en ProgramData"
    }
    if (-not $KeepProgramFiles) {
        Write-Host "  7. Borrar carpeta del nodo: $InstallRoot"
    } else {
        Write-Host "  7. Conservar archivos del nodo (-KeepProgramFiles)"
    }
    Write-Host ""
    Write-Host "NO se desinstala WireGuard ni Python del sistema."
    Write-Host ""
}

function Confirm-UninstallContinue {
    if ($Force) { return $true }
    $r = Read-Host "Continuar desinstalacion? (S/n)"
    return ($r -ne "n" -and $r -ne "N")
}

Assert-Admin

$TunnelName = ($TunnelName -replace '\\s', '').Trim()
if (-not $TunnelName) { $TunnelName = "wg0" }

$NodoInstallDir = Resolve-NodoInstallDir -InputPath $NodoDir
Invoke-RelaunchFromTempIfNeeded -InstallRoot $NodoInstallDir

Show-UninstallPlan -InstallRoot $NodoInstallDir -Tunnel $TunnelName
if (-not (Confirm-UninstallContinue)) {
    Write-Host "Cancelado."
    exit 0
}

Write-Host ""
Write-Host "[1/5] Deteniendo procesos API ..." -ForegroundColor Cyan
Stop-NodoApiProcesses -NodoDirPath $NodoInstallDir

Write-Host ""
Write-Host "[2/5] Quitando autostart API ..." -ForegroundColor Cyan
Remove-NodoApiAutostart -InstallRoot $NodoInstallDir
foreach ($name in $ApiTaskNames) {
    Remove-SchTaskNamed -Name $name
}

Write-Host ""
Write-Host "[3/5] Quitando tareas VPN resume/hibernacion ..." -ForegroundColor Cyan
Remove-WgResumeTasks -Tunnel $TunnelName
foreach ($name in $WgResumeTaskNames) {
    Remove-SchTaskNamed -Name $name
}

Write-Host ""
Write-Host "[4/5] WireGuard y datos Multishop ..." -ForegroundColor Cyan
if (-not $KeepVpn) {
    Remove-WireGuardVpn -PrimaryName $TunnelName
} else {
    Write-Host "Tunel WireGuard conservado (-KeepVpn)."
}
Remove-MultishopDataDirs

Write-Host ""
Write-Host "[5/5] Archivos del nodo ..." -ForegroundColor Cyan
if (-not $KeepProgramFiles) {
    Remove-NodoInstallTree -InstallRoot $NodoInstallDir
} else {
    Write-Host "Carpeta del nodo conservada (-KeepProgramFiles)."
}

Write-Host ""
Write-Host "Desinstalacion completada." -ForegroundColor Green
