# Wrapper: delega al instalador Windows unificado.

param(
    [string]$BundleDir = "",
    [string]$WgConfPath = "",
    [string]$EnvPath = "",
    [string]$TunnelName = "",
    [string]$InstallRoot = "",
    [switch]$SkipProgramFilesCopy,
    [switch]$SkipWgResume,
    [switch]$SkipApiAutostart,
    [switch]$RegisterWgResume,
    [switch]$KeepVenv,
    [switch]$NoStart,
    [switch]$NonInteractive
)

$full = Join-Path $PSScriptRoot "install-windows-full.ps1"
if (-not (Test-Path -LiteralPath $full)) {
    throw "No se encontró $full"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $full @PSBoundParameters
