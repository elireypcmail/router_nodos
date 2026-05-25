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
$DeployedScript = Join-Path $DeployDir "start-nodo-api.ps1"
$DeployedVbs = Join-Path $DeployDir "start-nodo-api.vbs"

if (-not (Test-Path $SourceScript)) {
    Write-Error "No se encontro $SourceScript"
}

$NodoDir = Resolve-NodoProjectDir -InputPath $NodoDir
$TunnelName = ($TunnelName -replace '\\s', '').Trim()
if (-not $TunnelName) { $TunnelName = "wg0" }

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

function Test-NodoApiTaskExists {
    param([string]$Name)
    if (-not $Name) { return $false }
    return (Invoke-SchTasksQuiet @("/Query", "/TN", $Name) -eq 0)
}

function Remove-NodoApiTaskNamed {
    param([string]$Name)
    if (Test-NodoApiTaskExists -Name $Name) {
        Invoke-SchTasksQuiet @("/Delete", "/TN", $Name, "/F") | Out-Null
    }
}

function Remove-NodoApiTasksLegacy {
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-API"
    Remove-NodoApiTaskNamed -Name "Multishop-Nodo-API-Logon"
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

function Test-NodoInProgramFiles {
    param([string]$Path)
    $norm = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\\')
    foreach ($root in @(${env:ProgramFiles}, ${env:ProgramFiles(x86)})) {
        if (-not $root) { continue }
        $root = $root.TrimEnd('\\')
        if ($norm.StartsWith($root + '\\', [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Install-NodoApiOnStartTask {
    if (-not (Test-NodoInProgramFiles -Path $NodoDir)) {
        Write-Host "ONSTART omitido (nodo fuera de Program Files; use carpeta Inicio + ONLOGON)."
        return
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
    } else {
        Write-Host "Tarea $TaskNameOnStart registrada (ONSTART SYSTEM, retraso 1:30)."
    }
}

function Install-NodoApiScheduledTask {
    if (-not (Test-Path $DeployedVbs)) {
        throw "Falta launcher $DeployedVbs"
    }
    $trCmd = 'wscript.exe //nologo "' + $DeployedVbs + '"'
    if ($trCmd.Length -gt 261) {
        throw "Comando /TR demasiado largo ($($trCmd.Length) chars, max 261)"
    }

    Remove-NodoApiTasksLegacy

    $runUser = "$env:USERDOMAIN\\$env:USERNAME"
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
    . $SourceScript
    try {
        Start-MultishopNodoApi -NodoDirOverride $NodoDir
        Write-Host "API iniciada en segundo plano." -ForegroundColor Green
        Write-Host "Log arranque: $DeployDir\\nodo-api-start.log"
        Write-Host "Salida API:  $DeployDir\\nodo-api.out.log"
        Write-Host "Errores:     $DeployDir\\nodo-api.err.log"
    } catch {
        Write-Host "No se pudo iniciar la API: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Revise $DeployDir\\nodo-api.err.log"
        throw
    }
}

if ($Uninstall) {
    Assert-AdminForInstall
    Remove-NodoApiTasksLegacy
    Remove-NodoApiStartupFolder
    if (Test-Path $DeployedVbs) { Remove-Item $DeployedVbs -Force }
    if (Test-Path $DeployedScript) { Remove-Item $DeployedScript -Force }
    if (Test-Path $DirFile) { Remove-Item $DirFile -Force }
    if (Test-Path $TunnelFile) { Remove-Item $TunnelFile -Force }
    Write-Host "Autostart API eliminado (tareas + carpeta Inicio)."
    exit 0
}

Assert-AdminForInstall

Deploy-NodoApiLauncher
Install-NodoApiStartupFolder
Install-NodoApiOnStartTask
Install-NodoApiScheduledTask

if ($StartNow) {
    Start-NodoApiBackground
}

Write-Host ""
Write-Host "Tras REINICIAR: la API arranca al encender (ONSTART) y al iniciar sesion (~1-3 min)."
Write-Host "Revise: Get-Content $DeployDir\\nodo-api-start.log -Tail 20"
Write-Host ""
Write-Host "Probar ahora:"
Write-Host "  wscript.exe //nologo `"$DeployedVbs`""
Write-Host "  schtasks /Run /TN `"$TaskName`""
Write-Host '  curl http://127.0.0.1:8443/api/health -H "Authorization: Bearer <TOKEN>"'
Write-Host ""
Write-Host "Desinstalar:"
Write-Host "  .\nodo-api-windows-install.ps1 -Uninstall"
