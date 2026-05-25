# Registra una tarea programada que reinicia WireGuard al salir de suspension/hibernacion.
# Ejecutar PowerShell COMO ADMINISTRADOR.
#
# Copia el script a C:\ProgramData\Multishop\ (ruta corta; schtasks /TR max 261 chars).
#
#   .\wg-resume-windows-install.ps1 -TunnelName "wg0"
#
# Desinstalar:
#   .\wg-resume-windows-install.ps1 -TunnelName "wg0" -Uninstall

param(
    [Parameter(Mandatory = $true)]
    [string]$TunnelName,

    [switch]$Uninstall,

    [int]$DelaySeconds = 30
)

$ErrorActionPreference = "Continue"

if ($TunnelName -is [System.Array]) {
    $TunnelName = [string]$TunnelName[-1]
}
if ($TunnelName -match 'interface:\s*(\S+)') {
    $TunnelName = $Matches[1]
}

$TaskName = "Multishop-WG-Resume"
$ScriptPath = (Resolve-Path (Join-Path $PSScriptRoot "wg-resume-windows.ps1")).Path
$DeployDir = Join-Path $env:ProgramData "Multishop"
$DeployedScript = Join-Path $DeployDir "wg-resume.ps1"
$DeployedCmd = Join-Path $DeployDir "wg-resume.cmd"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "No se encontro $ScriptPath"
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

function Test-WgResumeTaskExists {
    param([string]$Name)
    if (-not $Name) { return $false }
    return (Invoke-SchTasksQuiet @("/Query", "/TN", $Name) -eq 0)
}

function Remove-WgResumeTask {
    param([string]$Name)
    if (-not (Test-WgResumeTaskExists -Name $Name)) {
        return
    }
    Invoke-SchTasksQuiet @("/Delete", "/TN", $Name, "/F") | Out-Null
}

function Deploy-WgResumeLauncher {
    param([string]$TunnelName)
    if ($TunnelName -notmatch '^[\w\-]+$') {
        if ($TunnelName -match 'interface:\s*(\S+)') {
            $TunnelName = $Matches[1]
        } else {
            throw "Nombre de tunel invalido: $TunnelName (use letras, numeros, guion; ej. wg0)"
        }
    }
    if (-not (Test-Path $DeployDir)) {
        New-Item -ItemType Directory -Path $DeployDir -Force | Out-Null
    }
    Copy-Item $ScriptPath $DeployedScript -Force
    $cmdLines = @(
        "@echo off"
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$DeployedScript`" -TunnelName $TunnelName"
    )
    Set-Content -Path $DeployedCmd -Value ($cmdLines -join "`r`n") -Encoding ASCII
    Write-Host "Launcher: $DeployedCmd"
    return $DeployedCmd
}

function Remove-WgResumeLauncher {
    if (Test-Path $DeployedCmd) { Remove-Item $DeployedCmd -Force }
    if (Test-Path $DeployedScript) { Remove-Item $DeployedScript -Force }
    if (Test-Path $DeployDir) {
        $left = Get-ChildItem $DeployDir -ErrorAction SilentlyContinue
        if (-not $left) {
            Remove-Item $DeployDir -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-WgResumeTask {
    param(
        [string]$Name,
        [string]$Query,
        [string]$Label,
        [string]$TrCmd,
        [string]$Delay
    )
    if ($TrCmd.Length -gt 261) {
        throw "Comando /TR demasiado largo ($($TrCmd.Length) chars, max 261): $TrCmd"
    }
    Remove-WgResumeTask -Name $Name
    $schArgs = @(
        '/Create',
        '/TN', $Name,
        '/SC', 'ONEVENT',
        '/EC', 'System',
        '/MO', $Query,
        '/TR', $TrCmd,
        '/RU', 'SYSTEM',
        '/RL', 'HIGHEST',
        '/DELAY', $Delay,
        '/F'
    )
    $output = & schtasks.exe @schArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks /Create fallo para $Name : $output"
    }
    Write-Host "Tarea $Name registrada ($Label, retraso $Delay)."
}

if ($Uninstall) {
    Remove-WgResumeTask -Name $TaskName
    Remove-WgResumeTask -Name "${TaskName}-Hibernate"
    Remove-WgResumeLauncher
    Write-Host "Tareas Multishop-WG-Resume eliminadas."
    exit 0
}

$mins = [int][math]::Floor($DelaySeconds / 60)
$secs = [int]($DelaySeconds % 60)
$delay = $mins.ToString("0000") + ":" + $secs.ToString("00")
$trCmd = Deploy-WgResumeLauncher -TunnelName $TunnelName

New-WgResumeTask -Name $TaskName `
    -Query "*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=107]]" `
    -Label "resume desde suspension (107)" `
    -TrCmd $trCmd `
    -Delay $delay

New-WgResumeTask -Name "${TaskName}-Hibernate" `
    -Query "*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=42]]" `
    -Label "resume desde hibernacion (42)" `
    -TrCmd $trCmd `
    -Delay $delay

Write-Host ""
Write-Host "Tunel: $TunnelName"
Write-Host "Script: $DeployedScript"
Write-Host "Tarea ejecuta: $DeployedCmd"
Write-Host ""
Write-Host "Probar manualmente:"
Write-Host "  schtasks /Run /TN `"$TaskName`""
Write-Host "  wg show $TunnelName"
Write-Host "  ping 10.66.0.1"
Write-Host ""
Write-Host "Desinstalar:"
Write-Host "  .\wg-resume-windows-install.ps1 -TunnelName `"$TunnelName`" -Uninstall"
