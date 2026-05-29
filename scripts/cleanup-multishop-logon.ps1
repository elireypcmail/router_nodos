# Quita tareas legacy ONLOGON (*-Logon) y VBS en Inicio cuando el nodo esta en Program Files.
# En tienda solo deben quedar Multishop-Nodo-API y Multishop-Nodo-Huey (ONSTART).
#
# Ejecutar PowerShell COMO ADMINISTRADOR:
#   .\cleanup-multishop-logon.ps1
#   .\cleanup-multishop-logon.ps1 -NodoDir "C:\Program Files\Multishop\nodo" -StartNow

param(
    [string]$NodoDir = "",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

$envHelper = Join-Path $PSScriptRoot "nodo-env.ps1"
if (-not (Test-Path -LiteralPath $envHelper)) {
    throw "No se encontro $envHelper"
}
. $envHelper

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-NodoDirForCleanup {
    param([string]$InputPath = "")
    if ($InputPath -and (Test-Path -LiteralPath $InputPath)) {
        return (Resolve-Path -LiteralPath $InputPath).Path.TrimEnd('\')
    }
    $fromFile = Get-MultishopNodoDirFromProgramData
    if ($fromFile) { return $fromFile.TrimEnd('\') }
    $default = Join-Path ${env:ProgramFiles} "Multishop\nodo"
    if (Test-Path -LiteralPath $default) {
        return (Resolve-Path -LiteralPath $default).Path.TrimEnd('\')
    }
    throw "Use -NodoDir con la ruta del nodo (ej. C:\Program Files\Multishop\nodo)"
}

function Remove-MultishopStartupVbs {
    $names = @("Multishop-Nodo-API.vbs")
    foreach ($root in @(
            [Environment]::GetFolderPath("Startup"),
            [Environment]::GetFolderPath("CommonStartup")
        )) {
        if (-not $root) { continue }
        foreach ($vbs in $names) {
            $path = Join-Path $root $vbs
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force
                Write-Host "Eliminado Inicio: $path"
            }
        }
    }
}

if (-not (Test-IsAdmin)) {
    Write-Host "ERROR: ejecute como administrador." -ForegroundColor Red
    exit 1
}

$NodoDir = Resolve-NodoDirForCleanup -InputPath $NodoDir
Write-Host ""
Write-Host "=== Multishop: limpieza tareas Logon legacy ===" -ForegroundColor Cyan
Write-Host "NodoDir: $NodoDir"
Write-Host ""

Write-Host "[1/4] Deteniendo procesos duplicados ..."
Stop-MultishopNodoProcesses -NodoDir $NodoDir

Write-Host ""
Write-Host "[2/4] Deshabilitando tareas ONLOGON ..."
Disable-MultishopLogonTasks | Out-Null

Write-Host ""
Write-Host "[3/4] Eliminando tareas ONLOGON e Inicio ..."
$removed = 0
foreach ($taskName in @("Multishop-Nodo-API-Logon", "Multishop-Nodo-Huey-Logon")) {
    if (Remove-MultishopScheduledTaskNamed -Name $taskName -VerboseFail) {
        Write-Host "  Tarea eliminada: $taskName"
        $removed++
    }
}
if ($removed -eq 0) {
    $null = Remove-MultishopNodoScheduledTasks -Scope LogonOnly -Quiet
}
Remove-MultishopStartupVbs

Write-Host ""
Write-Host "[4/4] Verificacion ..."
$leftLogon = @()
foreach ($name in @("Multishop-Nodo-API-Logon", "Multishop-Nodo-Huey-Logon")) {
    if (Test-MultishopScheduledTaskExists -Name $name) {
        $leftLogon += $name
    }
}

Write-Host "Tareas ONSTART (deben existir):"
foreach ($name in @("Multishop-Nodo-API", "Multishop-Nodo-Huey")) {
    if (Test-MultishopScheduledTaskExists -Name $name) {
        Write-Host "  [OK] $name"
    } else {
        Write-Host "  [--] $name (no registrada; ejecute nodo-api-windows-install.ps1)" -ForegroundColor Yellow
    }
}

if ($leftLogon.Count -gt 0) {
    Write-Host ""
    Write-Host "ADVERTENCIA: siguen tareas Logon: $($leftLogon -join ', ')" -ForegroundColor Yellow
    Write-Host "Pruebe manualmente:" -ForegroundColor Yellow
    foreach ($name in $leftLogon) {
        Write-Host "  Unregister-ScheduledTask -TaskName '$name' -TaskPath '\' -Confirm:`$false"
    }
} else {
    Write-Host ""
    Write-Host "Sin tareas Logon legacy." -ForegroundColor Green
}

if ($StartNow) {
    Write-Host ""
    Write-Host "Arrancando API + Huey (un solo par de procesos) ..."
    $expectHuey = $false
    $envPath = Join-Path $NodoDir ".env"
    if (Test-Path -LiteralPath $envPath) {
        $envText = Get-Content -LiteralPath $envPath -Raw
        if ($envText -match '(?m)^\s*HUEY_ENABLED\s*=\s*true\s*$') {
            $expectHuey = $true
        }
    }
    if (Get-Command Start-MultishopNodoServicesNow -ErrorAction SilentlyContinue) {
        Start-MultishopNodoServicesNow -NodoDirPath $NodoDir -ExpectHuey:$expectHuey
    } else {
        Write-Warning "Start-MultishopNodoServicesNow no disponible; actualice nodo-env.ps1."
    }
} else {
    $counts = Get-MultishopNodoProcessCounts -NodoDir $NodoDir
    Write-Host ""
    Write-Host "Procesos actuales: API=$($counts.Api) Huey=$($counts.Huey)"
    Write-Host "Para arrancar ahora: .\cleanup-multishop-logon.ps1 -StartNow"
}

Write-Host ""
