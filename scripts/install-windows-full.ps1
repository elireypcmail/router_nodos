# Instala/configura nodo en Windows (6 pasos): copia, WireGuard, .env, venv, ExecutionPolicy, outbox, tareas API/VPN.
# Ejecutar como Administrador para instalación automática de servicio WireGuard y tareas.
#
# Si PowerShell bloquea scripts no firmados (ExecutionPolicy), use una de estas opciones:
#   install-windows.cmd                    (recomendado; doble clic -> Ejecutar como administrador)
#   powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
#
# Archivos descargados de Internet:  Unblock-File .\install-windows.ps1
#
#   .\install-windows.ps1 -BundleDir "C:\bundle-provisioning"
#   .\install-windows.ps1 -SkipWgResume
#   .\install-windows.ps1 -SkipApiAutostart   # no tarea Multishop-Nodo-API
#   .\install-windows.ps1 -SkipExecutionPolicy   # no cambiar ExecutionPolicy del usuario
#   .\install-windows.ps1 -KeepVenv   # no borrar venv existente
#   .\install-windows.ps1 -NoStart      # no arrancar API ahora (si hay tarea, igual se registra)
#
#   .\install-windows.ps1 -InstallRoot "D:\Multishop\router"   # otra ruta fija
#   .\install-windows.ps1 -SkipProgramFilesCopy                # quedarse en carpeta actual

param(
    [string]$BundleDir = "",
    [string]$WgConfPath = "",
    [string]$EnvPath = "",
    [string]$TunnelName = "",
    [string]$InstallRoot = "",
    [switch]$SkipProgramFilesCopy,
    [switch]$SkipWgResume,
    [switch]$SkipApiAutostart,
    [switch]$SkipExecutionPolicy,
    [switch]$RegisterWgResume,
    [switch]$KeepVenv,
    [switch]$NoStart,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

function Test-NodoProjectRoot {
    param([string]$Path)
    return (Test-Path -LiteralPath (Join-Path $Path "main.py"))
}

function Resolve-NodoProjectDir {
    param([string]$InputPath = "")
    if (-not $InputPath) {
        $InputPath = $PSScriptRoot
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
    throw "No se encontro la raiz del nodo (main.py). Ejecute desde la carpeta scripts\\ del proyecto."
}

$SourceNodoDir = Resolve-NodoProjectDir -InputPath $PSScriptRoot
$NodoDir = $SourceNodoDir
$ScriptsDir = Join-Path $SourceNodoDir "scripts"
$envHelperBootstrap = Join-Path $ScriptsDir 'nodo-env.ps1'
if (Test-Path -LiteralPath $envHelperBootstrap) {
    . $envHelperBootstrap
}
$script:BundleDirResolved = ""
$WireGuardExe = Join-Path ${env:ProgramFiles} "WireGuard\\wireguard.exe"
$WireGuardUrl = "https://www.wireguard.com/install/"
$HubVpnIp = "10.66.0.1"

$MinPythonMajor = 3
$MinPythonMinor = 10
$MaxPythonMinor = 13
$PreferredPythonMinor = 11
$WingetPython311Id = "Python.Python.3.11"

function Parse-PythonVersion {
    param([string]$VersionText)
    if (-not $VersionText) { return $null }
    $t = $VersionText.Trim()
    if ($t -match "Python\s+(\d+)\.(\d+)\.(\d+)") {
        return @{ Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Patch = [int]$Matches[3] }
    }
    return $null
}

function Test-PythonVersionSupported {
    param([hashtable]$V)
    if (-not $V) { return $false }
    if ($V.Major -ne $MinPythonMajor) { return $false }
    if ($V.Minor -lt $MinPythonMinor) { return $false }
    if ($V.Minor -gt $MaxPythonMinor) { return $false }
    return $true
}

function Try-GetPythonInfo {
    param(
        [string]$Exe,
        [string[]]$ArgsPrefix
    )
    try {
        $out = & $Exe @ArgsPrefix --version 2>&1
        $vt = ($out | Select-Object -First 1)
        $v = Parse-PythonVersion -VersionText $vt
        if ($v) {
            return @{ Exe = $Exe; ArgsPrefix = $ArgsPrefix; Version = $v; VersionText = $vt }
        }
    } catch {
        return $null
    }
    return $null
}

function Update-SessionPathFromRegistry {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($machinePath) { $parts += $machinePath }
    if ($userPath) { $parts += $userPath }
    if ($parts.Count -gt 0) {
        $env:Path = ($parts -join ";")
    }
}

function Test-IsPyLauncherExe {
    param([string]$Path)
    if (-not $Path) { return $false }
    return ((Split-Path -Leaf $Path) -ieq "py.exe")
}

function Get-Python311CandidatePaths {
    # Program Files primero: el autostart ONSTART corre como SYSTEM y no puede usar
    # Python instalado solo en el perfil del usuario (AppData\Local\...).
    $machinePaths = @(
        (Join-Path ${env:ProgramFiles} "Python311\python.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Python311-32\python.exe")
    )
    $userPaths = @(
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe")
    )
    $pythonCoreRoot = Join-Path $env:LocalAppData "Python"
    if (Test-Path -LiteralPath $pythonCoreRoot) {
        $userPaths += Get-ChildItem -LiteralPath $pythonCoreRoot -Directory -Filter "pythoncore-3.11*" -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "python.exe" }
    }
    return ($machinePaths + $userPaths) | Select-Object -Unique
}

function Select-PreferredPython311Info {
    param([array]$Candidates)
    if (-not $Candidates -or $Candidates.Count -eq 0) { return $null }
    foreach ($item in $Candidates) {
        $isMachine = if (Get-Command Test-PythonPathIsMachineWide -ErrorAction SilentlyContinue) {
            Test-PythonPathIsMachineWide -Path $item.Exe
        } else {
            ($item.Exe -notmatch '(?i)[\\/](Users|AppData)[\\/]')
        }
        if ($isMachine) { return $item }
    }
    return $Candidates[0]
}

function Find-Python311Info {
    $found = @()
    foreach ($candidate in Get-Python311CandidatePaths) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $info = Try-GetPythonInfo -Exe $candidate -ArgsPrefix @()
        if ($info -and $info.Version.Minor -eq $PreferredPythonMinor) {
            $info.UsePyLauncher = $false
            $found += $info
        }
    }

    $pyLaunchers = @(
        (Join-Path $env:WINDIR "py.exe")
    )
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd -and (Test-IsPyLauncherExe -Path $pyCmd.Source)) {
        $pyLaunchers += $pyCmd.Source
    }
    foreach ($pyExe in ($pyLaunchers | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $pyExe)) { continue }
        try {
            $resolvedLines = & $pyExe -3.11 -c "import sys; print(sys.executable)" 2>&1
            $resolved = ($resolvedLines | Where-Object { "$_" -match '\.exe$' } | Select-Object -Last 1)
            if ($resolved) {
                $resolved = $resolved.ToString().Trim()
                if (Test-Path -LiteralPath $resolved) {
                    $info = Try-GetPythonInfo -Exe $resolved -ArgsPrefix @()
                    if ($info -and $info.Version.Minor -eq $PreferredPythonMinor) {
                        $info.UsePyLauncher = $false
                        $found += $info
                    }
                }
            }
        } catch {
            # ignore; fallback to launcher mode below
        }

        $info = Try-GetPythonInfo -Exe $pyExe -ArgsPrefix @("-3.11")
        if ($info -and $info.Version.Minor -eq $PreferredPythonMinor) {
            $info.UsePyLauncher = $true
            $found += $info
        }
    }

    $unique = @()
    $seen = @{}
    foreach ($item in $found) {
        $key = $item.Exe.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $unique += $item
    }
    return (Select-PreferredPython311Info -Candidates $unique)
}

function Invoke-Python311 {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$PythonInfo,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$PythonArgs
    )

    if ($PythonInfo.UsePyLauncher) {
        & $PythonInfo.Exe @($PythonInfo.ArgsPrefix + $PythonArgs)
    } else {
        & $PythonInfo.Exe @PythonArgs
    }
    if ($LASTEXITCODE -ne 0) {
        $cmd = if ($PythonInfo.UsePyLauncher) {
            "$($PythonInfo.Exe) $($PythonInfo.ArgsPrefix -join ' ') $($PythonArgs -join ' ')"
        } else {
            "$($PythonInfo.Exe) $($PythonArgs -join ' ')"
        }
        throw "Python 3.11 fallo (codigo $LASTEXITCODE): $cmd"
    }
}

function Get-PythonCommand {
    $candidates = @()
    $pyExe = Join-Path $env:WINDIR "py.exe"
    if (Test-Path -LiteralPath $pyExe) {
        $candidates += @{ Exe = $pyExe; ArgsPrefix = @("-3.11") }
        $candidates += @{ Exe = $pyExe; ArgsPrefix = @("-3.12") }
        $candidates += @{ Exe = $pyExe; ArgsPrefix = @("-3.10") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += @{ Exe = $python.Source; ArgsPrefix = @() }
    }
    foreach ($c in $candidates) {
        if ($c.ArgsPrefix.Count -gt 0 -and -not (Test-IsPyLauncherExe -Path $c.Exe)) {
            continue
        }
        $info = Try-GetPythonInfo -Exe $c.Exe -ArgsPrefix $c.ArgsPrefix
        if ($info -and (Test-PythonVersionSupported -V $info.Version)) {
            return $info
        }
    }
    return $null
}

function Install-Python311WithWinget {
    Write-Host "Instalando Python 3.11 (winget $WingetPython311Id) ..." -ForegroundColor Cyan
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw @(
            "No se encontro winget para instalar Python 3.11."
            "Opciones:"
            "  winget install $WingetPython311Id -e"
            "  https://www.python.org/downloads/release/python-3119/ (Windows installer, marcar Add to PATH)"
        ) -join "`n"
    }

    $wingetArgs = @(
        'install', '--id', $WingetPython311Id, '-e', '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements'
    )
    if ((Get-Command Test-IsAdmin -ErrorAction SilentlyContinue) -and (Test-IsAdmin)) {
        $wingetArgs += '--scope', 'machine'
    }
    & $winget.Source @wingetArgs
    Update-SessionPathFromRegistry
    Start-Sleep -Seconds 3

    if ($LASTEXITCODE -ne 0) {
        $already = Find-Python311Info
        if ($already) {
            Write-Host "Python 3.11 ya instalado: $($already.VersionText)" -ForegroundColor Green
            return
        }
        throw "winget no pudo instalar Python 3.11 (codigo $LASTEXITCODE). Instale manualmente: winget install $WingetPython311Id -e"
    }
}

function Install-PythonAutomatically {
    Install-Python311WithWinget
}

function Get-VenvPythonVersion {
    param([string]$VenvPythonExe)
    if (-not (Test-Path -LiteralPath $VenvPythonExe)) { return $null }
    try {
        $out = & $VenvPythonExe --version 2>&1
        return Parse-PythonVersion -VersionText (($out | Select-Object -First 1) -as [string])
    } catch {
        return $null
    }
}

function Test-VenvNeedsRecreate {
    param(
        [string]$VenvPythonExe,
        [switch]$KeepVenv
    )
    if (-not (Test-Path -LiteralPath $VenvPythonExe)) {
        return $true
    }
    $venvDir = Split-Path (Split-Path $VenvPythonExe -Parent) -Parent
    if (Get-Command Test-VenvIsHealthyForSystemAutostart -ErrorAction SilentlyContinue) {
        if (-not (Test-VenvIsHealthyForSystemAutostart -VenvDir $venvDir -VenvPythonExe $VenvPythonExe)) {
            return $true
        }
    }
    if (-not $KeepVenv) {
        return $true
    }
    $venvVer = Get-VenvPythonVersion -VenvPythonExe $VenvPythonExe
    if (-not $venvVer) {
        return $true
    }
    if (-not (Test-PythonVersionSupported -V $venvVer)) {
        return $true
    }
    if ($venvVer.Minor -ne $PreferredPythonMinor) {
        return $true
    }
    return $false
}

function Ensure-Python311ForNodo {
    $info = Find-Python311Info
    if ($info -and (Get-Command Test-PythonPathIsMachineWide -ErrorAction SilentlyContinue) -and (Test-PythonPathIsMachineWide -Path $info.Exe)) {
        $via = if ($info.UsePyLauncher) { "launcher py -3.11" } else { "directo" }
        Write-Host "Python 3.11 OK (todos los usuarios): $($info.VersionText) ($via -> $($info.Exe))" -ForegroundColor Green
        return $info
    }

    if ($info) {
        Write-Host "Python 3.11 detectado solo en perfil de usuario: $($info.Exe)" -ForegroundColor Yellow
        Write-Host "  El autostart ONSTART (SYSTEM) requiere Python en Program Files; se instalara o buscara una copia para todos los usuarios." -ForegroundColor Yellow
    } else {
        $other = Get-PythonCommand
        if ($other) {
            Write-Host "Python detectado: $($other.VersionText) (no es 3.11; se instalara 3.11 para el nodo)." -ForegroundColor Yellow
        } else {
            Write-Host "Python 3.10-3.13 no encontrado; se instalara Python 3.11 ..." -ForegroundColor Yellow
        }
    }

    Install-Python311WithWinget

    $info2 = Find-Python311Info
    if ($info2 -and (Get-Command Test-PythonPathIsMachineWide -ErrorAction SilentlyContinue) -and (Test-PythonPathIsMachineWide -Path $info2.Exe)) {
        $via = if ($info2.UsePyLauncher) { "launcher py -3.11" } else { "directo" }
        Write-Host "Python 3.11 instalado (todos los usuarios): $($info2.VersionText) ($via -> $($info2.Exe))" -ForegroundColor Green
        return $info2
    }

    if ($info2) {
        throw @(
            "Python 3.11 sigue en el perfil del usuario ($($info2.Exe))."
            "Instale manualmente para todos los usuarios:"
            "  winget install $WingetPython311Id -e --scope machine"
            "  o desde python.org marque Install for all users (C:\Program Files\Python311\)"
        ) -join "`n"
    }

    throw @(
        "Python 3.11 sigue sin estar disponible tras la instalacion."
        "Cierre y reabra PowerShell como Administrador y vuelva a ejecutar install-windows.cmd"
        "O manualmente: winget install $WingetPython311Id -e --scope machine"
    ) -join "`n"
}

function Ensure-PythonCompatible {
    return (Ensure-Python311ForNodo)
}

function Enable-VenvPowerShellExecutionPolicy {
    $scope = "CurrentUser"
    $target = "RemoteSigned"
    try {
        $current = Get-ExecutionPolicy -Scope $scope -ErrorAction Stop
    } catch {
        Write-Warning "No se pudo leer ExecutionPolicy ($scope): $($_.Exception.Message)"
        return
    }

    $order = @{
        Undefined     = 0
        Restricted    = 1
        AllSigned     = 2
        RemoteSigned  = 3
        Unrestricted  = 4
        Bypass        = 5
    }
    $curRank = if ($order.ContainsKey($current.ToString())) { $order[$current.ToString()] } else { 0 }
    $tgtRank = $order[$target]

    if ($curRank -ge $tgtRank) {
        Write-Host "ExecutionPolicy $scope ya es $current (>= $target); sin cambios." -ForegroundColor Green
        return
    }

    Write-Host "Ajustando ExecutionPolicy ${scope}: $current -> $target (scripts en venv\Scripts, Activate.ps1, Huey) ..." -ForegroundColor Cyan
    Set-ExecutionPolicy -ExecutionPolicy $target -Scope $scope -Force
    $after = Get-ExecutionPolicy -Scope $scope
    Write-Host "ExecutionPolicy $scope = $after" -ForegroundColor Green
}

function Install-WireGuardTunnel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfPath,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Test-IsAdmin)) {
        throw "Instalar el tunel WireGuard automaticamente requiere PowerShell como Administrador."
    }
    if (-not (Test-Path -LiteralPath $WireGuardExe)) {
        throw "No se encontró WireGuard: $WireGuardExe"
    }
    if (-not (Test-Path -LiteralPath $ConfPath)) {
        throw "No se encontró conf WireGuard: $ConfPath"
    }
    if (-not $Name) {
        $Name = "wg0"
    }

    Write-Host "Instalando tunel WireGuard $Name como servicio ..." -ForegroundColor Cyan
    & $WireGuardExe /uninstalltunnelservice $Name 2>$null | Out-Null
    Start-Sleep -Seconds 2
    $out = & $WireGuardExe /installtunnelservice $ConfPath 2>&1
    if ($out) { $out | ForEach-Object { Write-Host $_ } }

    $serviceName = "WireGuardTunnel`$$Name"
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 1
        $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($svc) { break }
    }
    $svc2 = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (-not $svc2) {
        throw "No se creó el servicio $serviceName. Revise WireGuard / permisos / driver."
    }
    if ($svc2.Status -ne "Running") {
        try {
            Start-Service -Name $serviceName -ErrorAction Stop
        } catch {
            Write-Warning "No se pudo iniciar ${serviceName}: $($_.Exception.Message)"
        }
    }
    Write-Host "Tunel WireGuard activo: $serviceName" -ForegroundColor Green
}

function Test-HubReachable {
    if (Test-Connection -ComputerName $HubVpnIp -Count 2 -Quiet -ErrorAction SilentlyContinue) {
        Write-Host "Ping a $HubVpnIp OK." -ForegroundColor Green
        return $true
    }
    Write-Warning "No responde ping a $HubVpnIp. Revise el tunel en WireGuard."
    return $false
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-DefaultInstallRoot {
    if (Get-Command Get-MultishopDefaultInstallRoot -ErrorAction SilentlyContinue) {
        return Get-MultishopDefaultInstallRoot
    }
    return Join-Path ${env:ProgramFiles} "Multishop\\router"
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

function Remove-MultishopScheduledTaskIfExists {
    param([string]$Name)
    if (-not $Name) { return }
    foreach ($tn in @($Name, "\$Name")) {
        if (Invoke-SchTasksQuiet @("/Query", "/TN", $tn) -ne 0) { continue }
        Write-Host "  Eliminando tarea $tn ..."
        Invoke-SchTasksQuiet @("/Delete", "/TN", $tn, "/F") | Out-Null
        return
    }
}

function Remove-AllMultishopScheduledTasks {
    Write-Host "  Eliminando tareas ONSTART Multishop ..."
    $envHelper = Join-Path $ScriptsDir 'nodo-env.ps1'
    if (Test-Path -LiteralPath $envHelper) {
        . $envHelper
        if (Get-Command Remove-MultishopNodoScheduledTasks -ErrorAction SilentlyContinue) {
            Remove-MultishopNodoScheduledTasks -Quiet | Out-Null
            return
        }
    }
    $taskNames = if (Get-Command Get-MultishopScheduledTaskNames -ErrorAction SilentlyContinue) {
        Get-MultishopScheduledTaskNames
    } else {
        @('Multishop-Router-API', 'Multishop-Router-Huey')
    }
    foreach ($taskName in $taskNames) {
        Remove-MultishopScheduledTaskIfExists -Name $taskName
    }
}

function Install-NodoToProgramFiles {
    param(
        [string]$SourceDir,
        [string]$DestDir
    )
    $src = (Resolve-Path -LiteralPath $SourceDir).Path.TrimEnd('\\')
    if (-not $DestDir) {
        $DestDir = Get-DefaultInstallRoot
    }
    if (-not (Test-Path $DestDir)) {
        New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    }
    $dst = (Resolve-Path -LiteralPath $DestDir).Path.TrimEnd('\\')
    if ($src -ieq $dst) {
        Write-Host "Nodo ya esta en $dst"
        return $dst
    }
    Write-Host "Copiando nodo ..."
    Write-Host "  Origen:  $src"
    Write-Host "  Destino: $dst"
    $robocopyArgs = @(
        $src, $dst,
        "/E",
        "/XD", "venv", "__pycache__", ".git",
        "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np"
    )
    & robocopy.exe @robocopyArgs | Out-Host
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy fallo con codigo $LASTEXITCODE"
    }
    if (-not (Test-Path (Join-Path $dst "main.py"))) {
        throw "Copia incompleta: falta main.py en $dst"
    }
    Write-Host "Nodo instalado en $dst" -ForegroundColor Green
    return $dst
}

function Ensure-WireGuardInstalled {
    if (Test-Path $WireGuardExe) {
        return
    }
    Write-Host "WireGuard for Windows no esta instalado." -ForegroundColor Red
    Write-Host "Descarga: $WireGuardUrl"
    if ($NonInteractive) {
        throw "Instale WireGuard y vuelva a ejecutar el script."
    }
    $open = Read-Host "Abrir la pagina de descarga en el navegador? (S/n)"
    if ($open -ne "n" -and $open -ne "N") {
        Start-Process $WireGuardUrl
    }
    Read-Host "Instale WireGuard, reinicie PowerShell como Administrador y pulse Enter"
    if (-not (Test-Path $WireGuardExe)) {
        throw "Sigue sin encontrarse $WireGuardExe"
    }
}

function Find-ProvisioningFileHint {
    param(
        [string[]]$SearchDirs,
        [string[]]$RelativeNames
    )
    foreach ($searchDir in $SearchDirs) {
        foreach ($rel in $RelativeNames) {
            $candidate = Join-Path $searchDir $rel
            if (Test-Path -LiteralPath $candidate) {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
        }
    }
    return $null
}

function Get-ProvisioningSearchDirs {
    $dirs = @()
    $dirs += (Resolve-Path -LiteralPath $SourceNodoDir).Path
    $vpnDir = Join-Path $SourceNodoDir "vpn"
    if (Test-Path -LiteralPath $vpnDir) {
        $dirs += (Resolve-Path -LiteralPath $vpnDir).Path
    }
    if ($script:BundleDirResolved -and (Test-Path -LiteralPath $script:BundleDirResolved)) {
        $dirs += (Resolve-Path -LiteralPath $script:BundleDirResolved).Path
    }
    return @($dirs | Select-Object -Unique)
}

function Ensure-ParentDirectory {
    param([string]$FilePath)
    $dir = Split-Path -Parent $FilePath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

function Install-ProvisioningFile {
    param(
        [string]$SourcePath,
        [string]$DestPath,
        [string]$Label
    )
    Ensure-ParentDirectory -FilePath $DestPath
    Copy-Item -LiteralPath $SourcePath -Destination $DestPath -Force
    Write-Host "$Label guardado en $DestPath" -ForegroundColor Green
}

function Enable-OutboxTriggersIfDocker {
    param([string]$NodoDirPath)

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "Docker no disponible; se usará MySQL local según MYSQL_* en .env (producción)." -ForegroundColor DarkGray
        return $false
    }

    $hasContainer = (docker ps --format '{{.Names}}' | Select-String -Pattern '^mysql56-app$' -Quiet)
    if (-not $hasContainer) {
        Write-Host "Contenedor mysql56-app no encontrado; se usará MySQL local según MYSQL_* en .env." -ForegroundColor DarkGray
        return $false
    }

    Write-Warning "Contenedor mysql56-app detectado; use MYSQL_* del .env con apply_mysql_outbox_triggers.py (no pipe SQL directo)."
    return $false
}

function Parse-EnvFile {
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

function Invoke-MysqlUpgradeIfAvailable {
    param(
        [string]$MysqlBinDir = "C:\MySQL\MySQL Server 5.6\bin",
        [string]$MysqlUser = "root",
        [string]$MysqlPassword = ""
    )

    $upgradeExe = Join-Path $MysqlBinDir "mysql_upgrade.exe"
    if (-not (Test-Path -LiteralPath $upgradeExe)) {
        Write-Host "mysql_upgrade.exe no encontrado en $MysqlBinDir; omitiendo." -ForegroundColor DarkGray
        return
    }

    Write-Host "MySQL: mysql_upgrade (repara mysql.innodb_*_stats) ..." -ForegroundColor Cyan
    $args = @("-u", $MysqlUser)
    if ($MysqlPassword) {
        $args += @("-p$MysqlPassword")
    }
    & $upgradeExe @args
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "mysql_upgrade salió con código $LASTEXITCODE (continuando con triggers/outbox)."
    } else {
        Write-Host "mysql_upgrade OK." -ForegroundColor Green
    }
}

function Enable-OutboxTriggersWithPython {
    param(
        [string]$NodoDirPath,
        [string]$EnvFilePath,
        [string]$VenvPython
    )

    $sqlFile = Join-Path $NodoDirPath 'scripts\\mysql_outbox_triggers.sql'
    if (-not (Test-Path -LiteralPath $sqlFile)) {
        Write-Warning "No se encontró $sqlFile. Omitiendo activación de triggers/outbox."
        return
    }
    if (-not (Test-Path -LiteralPath $EnvFilePath)) {
        Write-Warning "No se encontró .env en $EnvFilePath. Omitiendo activación de triggers/outbox fuera de Docker."
        return
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Warning "No se encontró Python venv ($VenvPython). Omitiendo activación de triggers/outbox fuera de Docker."
        return
    }

    $envMap = Parse-EnvFile -Path $EnvFilePath
    $mysqlHost = $envMap["MYSQL_HOST"]
    $user = $envMap["MYSQL_USER"]
    $pass = $envMap["MYSQL_PASSWORD"]
    $db = $envMap["MYSQL_DATABASE"]
    $port = $envMap["MYSQL_PORT"]
    if (-not $port) { $port = "3306" }

    if (-not $mysqlHost -or -not $user -or -not $pass -or -not $db) {
        Write-Warning "Faltan MYSQL_* en .env (MYSQL_HOST/USER/PASSWORD/DATABASE). Omitiendo triggers/outbox fuera de Docker."
        return
    }

    Write-Host "Validando conectividad MySQL (${mysqlHost}:${port} / $db / usuario $user) ..." -ForegroundColor Cyan

    Invoke-MysqlUpgradeIfAvailable -MysqlUser $user -MysqlPassword $pass

    $applyScript = Join-Path $NodoDirPath 'scripts\apply_mysql_outbox_triggers.py'
    if (-not (Test-Path -LiteralPath $applyScript)) {
        Write-Warning "No se encontró $applyScript. Omitiendo triggers/outbox fuera de Docker."
        return
    }

    $env:MS_MYSQL_HOST = $mysqlHost
    $env:MS_MYSQL_USER = $user
    $env:MS_MYSQL_PASSWORD = $pass
    $env:MS_MYSQL_DATABASE = $db
    $env:MS_MYSQL_PORT = $port
    $env:MS_SQL_FILE = $sqlFile
    Remove-Item Env:MS_OUTBOX_SKIP_PREFLIGHT -ErrorAction SilentlyContinue
    $env:MS_OUTBOX_RECREATE_TABLES = "1"
    Write-Host "Outbox: desinstalar triggers Multishop, recrear tablas aux (MyISAM) y reinstalar ..." -ForegroundColor Cyan
    & $VenvPython $applyScript
    if ($LASTEXITCODE -ne 0) {
        throw "apply_mysql_outbox_triggers.py salió con código $LASTEXITCODE"
    }
    Remove-Item Env:MS_OUTBOX_RECREATE_TABLES -ErrorAction SilentlyContinue
}

# --- inicio ---

Write-Host ""
Write-Host "=== Multishop - instalacion nodo (Windows) ==="
Write-Host "Raiz detectada (origen): $SourceNodoDir"
Write-Host ""

if ($BundleDir) {
    $script:BundleDirResolved = (Resolve-Path -LiteralPath $BundleDir).Path
}

$InstallRoot = if ($SkipProgramFilesCopy) { $SourceNodoDir } elseif ($InstallRoot) { $InstallRoot } else { Get-DefaultInstallRoot }

Write-Host "Paso 1/6 - Ubicacion del nodo ..."
if (-not $SkipProgramFilesCopy) {
    $NodoDir = Install-NodoToProgramFiles -SourceDir $SourceNodoDir -DestDir $InstallRoot
    $NodoDir = Resolve-NodoProjectDir -InputPath $NodoDir
    $ScriptsDir = Join-Path $NodoDir "scripts"
} else {
    $NodoDir = Resolve-NodoProjectDir -InputPath $NodoDir
    $ScriptsDir = Join-Path $NodoDir "scripts"
}
Write-Host "Raiz del nodo: $NodoDir"

$searchDirs = Get-ProvisioningSearchDirs

Write-Host ""
Write-Host "Paso 2/6 - VPN (WireGuard) [opcional] ..."

$wgSource = $null
if ($WgConfPath -and (Test-Path -LiteralPath $WgConfPath)) {
    $wgSource = (Resolve-Path -LiteralPath $WgConfPath).Path
} else {
    $wgSource = Find-ProvisioningFileHint -SearchDirs $searchDirs -RelativeNames @('vpn\\wg0.conf', 'wg0.conf', 'vpn\\w0g.conf', 'w0g.conf')
}

$effectiveTunnel = $TunnelName
if (-not $effectiveTunnel) { $effectiveTunnel = 'wg0' }

if ($wgSource) {
    Ensure-WireGuardInstalled

    $vpnDir = Join-Path $NodoDir 'vpn'
    if (-not (Test-Path -LiteralPath $vpnDir)) {
        New-Item -ItemType Directory -Path $vpnDir -Force | Out-Null
    }
    $wgDest = Join-Path $vpnDir ("$effectiveTunnel.conf")
    Install-ProvisioningFile -SourcePath $wgSource -DestPath $wgDest -Label 'WireGuard'

    if (Test-IsAdmin) {
        Install-WireGuardTunnel -ConfPath $wgDest -Name $effectiveTunnel
        Test-HubReachable | Out-Null
    } else {
        Write-Warning "Sin Administrador: no se puede instalar el servicio WireGuard automaticamente."
        Write-Host "Importe manualmente en WireGuard GUI y active el tunel:" -ForegroundColor Yellow
        Write-Host "  $wgDest"
    }
} else {
    Write-Warning "No se encontró wg0.conf. Continuando sin VPN (red normal)."
    $effectiveTunnel = ""
}

Write-Host ""
Write-Host "Paso 3/6 - Config (.env) [opcional] ..."

$envSource = $null
if ($EnvPath -and (Test-Path -LiteralPath $EnvPath)) {
    $envSource = (Resolve-Path -LiteralPath $EnvPath).Path
} else {
    $envSource = Find-ProvisioningFileHint -SearchDirs $searchDirs -RelativeNames @('env.txt', 'env', '.env')
}

if ($envSource) {
    $envDest = Join-Path $NodoDir '.env'
    Install-ProvisioningFile -SourcePath $envSource -DestPath $envDest -Label '.env'
} else {
    Write-Warning "No se encontró .env/env/env.txt. El nodo puede arrancar, pero no podrá comunicarse con el hub sin HUB_BASE_URL."
}

Write-Host ""
Write-Host "Paso 4/6 - Python 3.11 + venv ..."

$pythonInfo = Ensure-Python311ForNodo

$venvDir = Join-Path $NodoDir 'venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

if (Test-VenvNeedsRecreate -VenvPythonExe $venvPython -KeepVenv:$KeepVenv) {
    if (Test-Path -LiteralPath $venvDir) {
        $venvVer = Get-VenvPythonVersion -VenvPythonExe $venvPython
        $venvHome = if (Get-Command Get-VenvPyvenvHome -ErrorAction SilentlyContinue) {
            Get-VenvPyvenvHome -VenvDir $venvDir
        } else { $null }
        if ($venvHome -and (Get-Command Test-PythonPathIsMachineWide -ErrorAction SilentlyContinue) -and -not (Test-PythonPathIsMachineWide -Path $venvHome)) {
            Write-Host "Recreando venv (pyvenv.cfg apunta a perfil de usuario: $venvHome) ..." -ForegroundColor Yellow
        } elseif ($venvVer) {
            Write-Host "Recreando venv (tenia Python $($venvVer.Major).$($venvVer.Minor); se usa 3.11) ..." -ForegroundColor Yellow
        } else {
            Write-Host "Recreando venv ..." -ForegroundColor Yellow
        }
        try {
            Remove-Item -LiteralPath $venvDir -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            # ignore
        }
    }
    Write-Host "Creando venv en $venvDir ..." -ForegroundColor Cyan
    Invoke-Python311 -PythonInfo $pythonInfo '-m' 'venv' $venvDir
} else {
    Write-Host "venv existente OK (Python 3.11, -KeepVenv)." -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "No se creo $venvPython. Revise que Python 3.11 tenga el modulo venv (instalacion completa, no embeddable)."
}

if (-not (Test-VenvPythonHasPip -VenvPythonExe $venvPython)) {
    Write-Host "pip no disponible en venv; ejecutando ensurepip ..." -ForegroundColor Yellow
    & $venvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        throw "ensurepip fallo (codigo $LASTEXITCODE). Recree el venv con Python de Program Files."
    }
}

Write-Host "Instalando dependencias (pip) ..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $NodoDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw "pip install fallo (codigo $LASTEXITCODE)"
}

& $venvPython -c "import pymysql" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "El venv no puede importar pymysql tras pip install. Revise $venvDir y requirements.txt."
}

if (Get-Command Ensure-NodoVenvSystemAccess -ErrorAction SilentlyContinue) {
    Ensure-NodoVenvSystemAccess -VenvDir $venvDir
    Write-Host "  Permisos SYSTEM en venv OK." -ForegroundColor Green
}

$envHelperEarly = Join-Path $ScriptsDir 'nodo-env.ps1'
if (Test-Path -LiteralPath $envHelperEarly) {
    . $envHelperEarly
    if (Get-Command Ensure-NodoWritableDataDir -ErrorAction SilentlyContinue) {
        Ensure-NodoWritableDataDir -NodoDir $NodoDir
        Write-Host "  Carpeta data\ lista (SQLite Huey/sync; permisos SYSTEM)." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Paso 5/6 - PowerShell (venv Scripts) ..."
if ($SkipExecutionPolicy) {
    Write-Host "Omitido (-SkipExecutionPolicy). Para Huey/Activate.ps1 manualmente:"
    Write-Host '  Set-ExecutionPolicy RemoteSigned -Scope CurrentUser'
} else {
    try {
        Enable-VenvPowerShellExecutionPolicy
    } catch {
        Write-Warning "No se pudo aplicar ExecutionPolicy RemoteSigned (CurrentUser): $($_.Exception.Message)"
        Write-Host '  Ejecute manualmente: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser' -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Paso 6/6 - Triggers/outbox (MySQL local o Docker dev) [opcional] ..."
$triggersInDocker = Enable-OutboxTriggersIfDocker -NodoDirPath $NodoDir
if (-not $triggersInDocker) {
    try {
        $envFileForDb = Join-Path $NodoDir '.env'
        Enable-OutboxTriggersWithPython -NodoDirPath $NodoDir -EnvFilePath $envFileForDb -VenvPython $venvPython
    } catch {
        Write-Warning "No se pudieron activar triggers/outbox en MySQL: $($_.Exception.Message)"
        Write-Host ""
        Write-Host "Verifique MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD y MYSQL_DATABASE en .env." -ForegroundColor Yellow
        Write-Host "El usuario MySQL necesita CREATE TRIGGER y acceso a la base del ERP." -ForegroundColor Yellow
        Write-Host "Puede reintentar manualmente:" -ForegroundColor Yellow
        Write-Host "  cd `"$NodoDir`"" -ForegroundColor Gray
        Write-Host "  .\venv\Scripts\python.exe .\scripts\apply_mysql_outbox_triggers.py" -ForegroundColor Gray
        Write-Host "  (defina antes MS_MYSQL_* y MS_SQL_FILE; el instalador las asigna al ejecutar el paso 6)" -ForegroundColor Gray
    }
}

if ($effectiveTunnel -and (-not $SkipWgResume) -and (Test-IsAdmin)) {
    $wgResume = Join-Path $ScriptsDir 'wg-resume-windows-install.ps1'
    if (Test-Path -LiteralPath $wgResume) {
        Write-Host ""
        Write-Host "Registrando tareas VPN resume/hibernacion ..." -ForegroundColor Cyan
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wgResume -TunnelName $effectiveTunnel | Out-Host
    }
}

if (-not $SkipApiAutostart) {
    $apiAuto = Join-Path $ScriptsDir 'nodo-api-windows-install.ps1'
    if (Test-Path -LiteralPath $apiAuto) {
        Write-Host ""
        Write-Host "Registrando autostart API (solo ONSTART en Program Files) ..." -ForegroundColor Cyan
        $ver = Select-String -Path $apiAuto -Pattern 'MultishopWindowsInstallVersion\s*=\s*"([^"]+)"' |
            ForEach-Object { $_.Matches[0].Groups[1].Value } |
            Select-Object -First 1
        if ($ver) {
            Write-Host "  nodo-api-windows-install.ps1 version: $ver"
        } else {
            Write-Warning "  nodo-api-windows-install.ps1 sin version (bundle viejo)."
        }
        Remove-AllMultishopScheduledTasks
        $args = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $apiAuto,
            "-NodoDir", $NodoDir
        )
        if ($effectiveTunnel) {
            $args += "-TunnelName"
            $args += $effectiveTunnel
        }
        if (-not $NoStart) {
            $args += "-StartNow"
        }
        & powershell.exe @args
        $apiInstallExit = $LASTEXITCODE
        if ($apiInstallExit -ne 0) {
            throw "nodo-api-windows-install.ps1 fallo (exit $apiInstallExit). Revise ProgramData\Multishop\*.log"
        }
        if (-not $NoStart) {
            $envHelper = Join-Path $ScriptsDir 'nodo-env.ps1'
            if (Test-Path -LiteralPath $envHelper) {
                . $envHelper
                Start-Sleep -Seconds 2
                $counts = Get-MultishopNodoProcessCounts -NodoDir $NodoDir
                Write-Host "  Verificacion post-install: API=$($counts.Api) Huey=$($counts.Huey)"
                if ($counts.Api -gt 1 -or $counts.Huey -gt 1) {
                    Write-Warning "Procesos duplicados (API=$($counts.Api) Huey=$($counts.Huey)). Re-ejecute nodo-api-windows-install.ps1 -StartNow para consolidar."
                }
                if ($counts.Api -lt 1) {
                    $logBase = if (Get-Command Get-MultishopApiLogBasename -ErrorAction SilentlyContinue) {
                        Get-MultishopApiLogBasename
                    } else { 'router-api' }
                    $deployLog = if (Get-Command Get-MultishopDeployRoot -ErrorAction SilentlyContinue) {
                        Get-MultishopDeployRoot
                    } else {
                        Join-Path $env:ProgramData 'Multishop\router'
                    }
                    Write-Warning (@(
                        "La API no arranco tras -StartNow.",
                        "Revise $deployLog\$logBase-start.log y $logBase.err.log",
                        "La tarea ONSTART quedo registrada; corrija .env/certs y ejecute:",
                        "  wscript.exe //nologo `"$deployLog\start-api.vbs`""
                    ) -join "`n  ")
                }
            }
        }
        Write-Host "  Autostart registrado." -ForegroundColor Green
    }
}

Write-Host "Nodo Windows listo en $(Get-MultishopDefaultInstallRoot)."
Write-Host "Arranque API: $(Join-Path $venvDir 'Scripts\\python') $(Join-Path $NodoDir 'main.py')"
Write-Host ""
Write-Host "Conexion directa (fork router): HUEY_ENABLED=false en .env; solo API + tarea $(Get-MultishopApiScheduledTaskName)."
Write-Host "Convive con Multishop\\nodo en la misma PC (carpetas y tareas distintas)."
