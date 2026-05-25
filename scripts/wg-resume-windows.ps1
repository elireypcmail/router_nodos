# Reinicia el tunel WireGuard tras suspension/hibernacion (Windows).
# Requiere WireGuard for Windows instalado.
#
# Uso manual:
#   .\wg-resume-windows.ps1 -TunnelName "Tariba"
#
# -TunnelName = nombre del archivo .conf sin extension (ej. wg0 -> servicio WireGuardTunnel$wg0).
# Opcional: -ConfPath "C:\ruta\wg0.conf" si no existe servicio y quieres reinstalar.
#
# Lo invoca la tarea programada Multishop-WG-Resume (wg-resume-windows-install.ps1).

param(
    [Parameter(Mandatory = $true)]
    [string]$TunnelName,

    [string]$ConfPath = ""
)

$ErrorActionPreference = "Stop"

$wireguardExe = Join-Path ${env:ProgramFiles} "WireGuard\wireguard.exe"
$serviceName = "WireGuardTunnel`$$TunnelName"

function Test-TunnelHandshake {
    $wg = Get-Command wg -ErrorAction SilentlyContinue
    if (-not $wg) {
        return
    }
    Write-Host "--- wg show $TunnelName ---"
    & wg show $TunnelName
}

if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) {
    Write-Host "Reiniciando servicio $serviceName ..."
    Restart-Service -Name $serviceName -Force
    Start-Sleep -Seconds 2
    Test-TunnelHandshake
    Write-Host "Listo. Prueba: ping 10.66.0.1"
    exit 0
}

if ($ConfPath -and (Test-Path $ConfPath)) {
    if (-not (Test-Path $wireguardExe)) {
        Write-Error "No se encontro $wireguardExe. Instala WireGuard for Windows."
    }
    Write-Host "Servicio no encontrado; reinstalando tunel desde $ConfPath ..."
    & $wireguardExe /uninstalltunnelservice $TunnelName 2>$null
    Start-Sleep -Seconds 1
    & $wireguardExe /installtunnelservice $ConfPath
    Test-TunnelHandshake
    Write-Host "Listo."
    exit 0
}

Write-Error "No se encontro el servicio $serviceName. Abra WireGuard, desactive y active el tunel $TunnelName. O ejecute: .\wg-resume-windows.ps1 -TunnelName `\"$TunnelName`\" -ConfPath `\"C:\ruta\wg0.conf`\""
