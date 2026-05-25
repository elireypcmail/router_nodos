# Lectura de .env del nodo (NODO_PORT, etc.) — dot-source desde otros scripts en scripts\

function Read-MultishopEnvFile {
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

function Get-MultishopNodoDirFromProgramData {
    $dirFile = Join-Path $env:ProgramData "Multishop\nodo-dir.txt"
    if (-not (Test-Path -LiteralPath $dirFile)) {
        return $null
    }
    $dir = (Get-Content -LiteralPath $dirFile -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not $dir) { return $null }
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    return $dir
}

function Get-MultishopNodoApiPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodoDir,

        [int]$DefaultPort = 8443
    )
    $envPath = Join-Path $NodoDir ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        return $DefaultPort
    }
    $map = Read-MultishopEnvFile -Path $envPath
    $raw = $map["NODO_PORT"]
    if (-not $raw) {
        return $DefaultPort
    }
    $parsed = 0
    if ([int]::TryParse($raw.Trim(), [ref]$parsed) -and $parsed -gt 0 -and $parsed -le 65535) {
        return $parsed
    }
    Write-Warning "NODO_PORT invalido en .env ($raw); usando $DefaultPort"
    return $DefaultPort
}
