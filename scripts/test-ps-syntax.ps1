# Verifica sintaxis de scripts .ps1 en esta carpeta (sin ejecutar el instalador).
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-ps-syntax.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$files = Get-ChildItem -LiteralPath $root -Filter "*.ps1" -File |
    Where-Object { $_.Name -ne "test-ps-syntax.ps1" }

$failed = 0
foreach ($f in $files) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $f.FullName,
        [ref]$tokens,
        [ref]$errors
    )
    if ($errors -and $errors.Count -gt 0) {
        $failed++
        Write-Host "FAIL $($f.Name)" -ForegroundColor Red
        foreach ($e in $errors) {
            Write-Host "  $($e.Extent.StartLineNumber):$($e.Extent.StartColumnNumber) $($e.ErrorId) $($e.Message)"
        }
    } else {
        Write-Host "OK   $($f.Name)" -ForegroundColor Green
    }
}

if ($failed -gt 0) {
    Write-Host ""
    Write-Host "$failed archivo(s) con errores de sintaxis." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Todos los scripts .ps1 pasaron el analizador de sintaxis." -ForegroundColor Green
exit 0
