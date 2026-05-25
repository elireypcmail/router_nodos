# Instala/configura nodo en Windows: WireGuard (opcional), .env (opcional), venv, tareas resume VPN, API.
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
#   .\install-windows.ps1 -KeepVenv   # no borrar venv existente
#   .\install-windows.ps1 -NoStart      # no arrancar API ahora (si hay tarea, igual se registra)
#
#   .\install-windows.ps1 -InstallRoot "D:\Multishop\nodo"   # otra ruta fija
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
$script:BundleDirResolved = ""
$WireGuardExe = Join-Path ${env:ProgramFiles} "WireGuard\\wireguard.exe"
$WireGuardUrl = "https://www.wireguard.com/install/"
$HubVpnIp = "10.66.0.1"

$MinPythonMajor = 3
$MinPythonMinor = 10

function Parse-PythonVersion {
    param([string]$VersionText)
    if (-not $VersionText) { return $null }
    $t = $VersionText.Trim()
    if ($t -match "Python\s+(\d+)\.(\d+)\.(\d+)") {
        return @{ Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Patch = [int]$Matches[3] }
    }
    return $null
}

function Test-PythonMeetsMinimum {
    param([hashtable]$V)
    if (-not $V) { return $false }
    if ($V.Major -gt $MinPythonMajor) { return $true }
    if ($V.Major -lt $MinPythonMajor) { return $false }
    return ($V.Minor -ge $MinPythonMinor)
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

function Get-PythonCommand {
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += @{ Exe = $py.Source; ArgsPrefix = @("-3") }
        $candidates += @{ Exe = $py.Source; ArgsPrefix = @("-3.11") }
        $candidates += @{ Exe = $py.Source; ArgsPrefix = @("-3.10") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += @{ Exe = $python.Source; ArgsPrefix = @() }
    }
    foreach ($c in $candidates) {
        $info = Try-GetPythonInfo -Exe $c.Exe -ArgsPrefix $c.ArgsPrefix
        if ($info -and (Test-PythonMeetsMinimum -V $info.Version)) {
            return $info
        }
    }
    return $null
}

function Install-PythonAutomatically {
    Write-Host "Python $MinPythonMajor.$MinPythonMinor+ requerido. Intentando instalar automaticamente ..." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "No se encontró winget. Instale Python manualmente (recomendado 3.11+) y vuelva a ejecutar."
    }
    & $winget.Source install --id Python.Python.3.11 -e --source winget
    if ($LASTEXITCODE -ne 0) {
        throw "winget no pudo instalar Python (codigo $LASTEXITCODE). Instale Python manualmente y vuelva a ejecutar."
    }
}

function Ensure-PythonCompatible {
    $info = Get-PythonCommand
    if ($info) {
        Write-Host "Python OK: $($info.VersionText) ($($info.Exe) $($info.ArgsPrefix -join ' '))" -ForegroundColor Green
        return $info
    }

    Install-PythonAutomatically

    $info2 = Get-PythonCommand
    if ($info2) {
        Write-Host "Python instalado: $($info2.VersionText)" -ForegroundColor Green
        return $info2
    }
    throw "Python sigue sin estar disponible tras instalación. Cierre y reabra PowerShell e intente de nuevo."
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
            Write-Warning "No se pudo iniciar $serviceName: $($_.Exception.Message)"
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
    return Join-Path ${env:ProgramFiles} "Multishop\\nodo"
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
        Write-Warning "Docker no está instalado. Omitiendo activación de triggers/outbox."
        return $false
    }

    $hasContainer = (docker ps --format '{{.Names}}' | Select-String -Pattern '^mysql56-app$' -Quiet)
    if (-not $hasContainer) {
        Write-Warning "No se encontró el contenedor Docker mysql56-app. Omitiendo activación de triggers/outbox."
        return $false
    }

    Write-Host "Activando triggers/outbox en MySQL (Docker: mysql56-app, DB: mi_base_restaurada)..."
    Write-Host "Tablas CDC: sinv, sprv, ventas/ventasd, factura/facturad, kardex/kardexd, comprasdbf, catego"

    $sqlFile = Join-Path $NodoDirPath 'scripts\\mysql_outbox_triggers.sql'
    if (-not (Test-Path -LiteralPath $sqlFile)) {
        Write-Warning "No se encontró $sqlFile. Omitiendo activación de triggers/outbox."
        return $false
    }

    Get-Content $sqlFile | docker exec -i mysql56-app mysql -u root -pmultishop -D mi_base_restaurada
    return $true
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
    $host = $envMap["MYSQL_HOST"]
    $user = $envMap["MYSQL_USER"]
    $pass = $envMap["MYSQL_PASSWORD"]
    $db = $envMap["MYSQL_DATABASE"]
    $port = $envMap["MYSQL_PORT"]
    if (-not $port) { $port = "3306" }

    if (-not $host -or -not $user -or -not $pass -or -not $db) {
        Write-Warning "Faltan MYSQL_* en .env (MYSQL_HOST/USER/PASSWORD/DATABASE). Omitiendo triggers/outbox fuera de Docker."
        return
    }

    Write-Host "Validando conectividad MySQL ($host:$port / $db / usuario $user) ..." -ForegroundColor Cyan

    $pyCode = @'
import os
import mysql.connector
from mysql.connector import errors

def parse_sql_statements(text: str):
    delim = ';'
    buff = []
    stmts = []
    for raw in text.splitlines():
        line = raw.rstrip('\r\n')
        stripped = line.strip()
        if stripped.upper().startswith('DELIMITER '):
            delim = stripped.split(None, 1)[1].strip()
            continue
        buff.append(line)
        joined = "\n".join(buff).strip()
        if not joined:
            buff = []
            continue
        if delim != ';':
            if stripped.endswith(delim):
                stmt = "\n".join(buff)
                stmt = stmt.rsplit(delim, 1)[0].strip()
                if stmt:
                    stmts.append(stmt + ';')
                buff = []
        else:
            if stripped.endswith(';'):
                stmt = "\n".join(buff).strip()
                if stmt:
                    stmts.append(stmt)
                buff = []
    tail = "\n".join(buff).strip()
    if tail:
        stmts.append(tail)
    return [s for s in stmts if s.strip()]

host = os.environ['MS_MYSQL_HOST']
user = os.environ['MS_MYSQL_USER']
password = os.environ['MS_MYSQL_PASSWORD']
database = os.environ['MS_MYSQL_DATABASE']
port = int(os.environ.get('MS_MYSQL_PORT', '3306'))
sql_path = os.environ['MS_SQL_FILE']

def preflight():
    try:
        cn = mysql.connector.connect(host=host, port=port, user=user, password=password, autocommit=True)
    except errors.Error as e:
        raise RuntimeError(f"No se pudo conectar a MySQL en {host}:{port} con el usuario {user}: {e}")
    try:
        cur = cn.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()
        cur.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (database,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"La base de datos '{database}' no existe o el usuario no tiene permisos para verla")
    finally:
        try:
            cn.close()
        except Exception:
            pass

preflight()

with open(sql_path, 'r', encoding='utf-8') as f:
    sql_text = f.read()

stmts = parse_sql_statements(sql_text)
if not stmts:
    raise RuntimeError('No se encontraron statements en el SQL')

cn = mysql.connector.connect(host=host, port=port, user=user, password=password, database=database, autocommit=False)
try:
    cur = cn.cursor()
    for stmt in stmts:
        s = stmt.strip()
        if not s:
            continue
        cur.execute(s)
    cn.commit()
finally:
    try:
        cn.close()
    except Exception:
        pass
'

    $env:MS_MYSQL_HOST = $host
    $env:MS_MYSQL_USER = $user
    $env:MS_MYSQL_PASSWORD = $pass
    $env:MS_MYSQL_DATABASE = $db
    $env:MS_MYSQL_PORT = $port
    $env:MS_SQL_FILE = $sqlFile
    Write-Host "Aplicando triggers/outbox ..." -ForegroundColor Cyan
    & $VenvPython -c $pyCode
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

Write-Host "Paso 1/5 - Ubicacion del nodo ..."
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
Write-Host "Paso 2/5 - VPN (WireGuard) [opcional] ..."

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
Write-Host "Paso 3/5 - Config (.env) [opcional] ..."

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
Write-Host "Paso 4/5 - API Python (venv) ..."

$pythonInfo = Ensure-PythonCompatible

$venvDir = Join-Path $NodoDir 'venv'
if ((Test-Path -LiteralPath $venvDir) -and (-not $KeepVenv)) {
    try {
        Remove-Item -LiteralPath $venvDir -Recurse -Force -ErrorAction SilentlyContinue
    } catch {
        # ignore
    }
}

$venvPython = Join-Path $venvDir 'Scripts\\python.exe'
$venvPip = Join-Path $venvDir 'Scripts\\pip.exe'

& $pythonInfo.Exe @($pythonInfo.ArgsPrefix + @('-m', 'venv', $venvDir))
& $venvPip install -r (Join-Path $NodoDir 'requirements.txt')

Write-Host ""
Write-Host "Paso 5/5 - Triggers/outbox (Docker o local) [opcional] ..."
$triggersInDocker = Enable-OutboxTriggersIfDocker -NodoDirPath $NodoDir
if (-not $triggersInDocker) {
    try {
        $envFileForDb = Join-Path $NodoDir '.env'
        Enable-OutboxTriggersWithPython -NodoDirPath $NodoDir -EnvFilePath $envFileForDb -VenvPython $venvPython
    } catch {
        Write-Warning "No se pudieron activar triggers/outbox fuera de Docker: $($_.Exception.Message)"
        Write-Host ""
        Write-Host "Si su MySQL NO está en Docker, verifique MYSQL_* en .env y que el usuario tenga permisos de CREATE TRIGGER." -ForegroundColor Yellow
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
        Write-Host "Registrando autostart API (tareas + carpeta Inicio) ..." -ForegroundColor Cyan
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
        & powershell.exe @args | Out-Host
    }
}

Write-Host ""
Write-Host "Nodo Windows listo. Arranque API: $(Join-Path $venvDir 'Scripts\\python') $(Join-Path $NodoDir 'main.py')"
Write-Host ""
Write-Host "Huey (opcional, recomendado para reintentos de outbox):"
Write-Host "- En .env: HUEY_ENABLED=true (y configure HUB_* + MYSQL_*)"
Write-Host "- Arranque Huey consumer: $(Join-Path $venvDir 'Scripts\\python') -m huey.bin.huey_consumer huey_tasks.huey"
