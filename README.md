# Multishop Nodo API

Nodo local de Multishop (FastAPI/Python) para operar con una **BD MySQL local**.

Este fork está enfocado en una **superficie mínima**: el hub accede al nodo por red privada (VPN o red interna) para lectura/escritura controlada de maestros y lectura de transaccional.

---

## Tabla de contenido

- [Características](#características)
- [Alcance del fork](#alcance-del-fork)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Requisitos](#requisitos)
- [Configuración (env.txt/.env)](#configuración-envtxtenv)
- [Instalación](#instalación)
  - [Windows (modo pro)](#windows-modo-pro)
  - [Linux](#linux)
- [Ejecución](#ejecución)
  - [Arrancar API](#arrancar-api)
- [Notas sobre WireGuard vs red normal](#notas-sobre-wireguard-vs-red-normal)
- [Verificación y troubleshooting](#verificación-y-troubleshooting)
- [Seguridad](#seguridad)

---

## Alcance del fork

Este nodo expone únicamente una API privada para que el hub pueda:

- consultar estado (`health`)
- operar maestros (categorías, proveedores, inventario) con CRU
  - **DELETE no está permitido** (responde `405`)
- consultar transaccional (compras, ventas, movimientos, lotes) en modo lectura

---

## API (resumen)

Rutas montadas desde `main.py` (ver `routes/`):

- `GET /api/health`
- `GET/POST/PATCH` de maestros (según recurso)
- `GET` transaccional

---

## Estructura del proyecto

Layout por dominio: ver [docs/arquitectura-python.md](docs/arquitectura-python.md).

- `main.py`: entry point de la API
- `core/`, `db/`: lógica de negocio
- `routes/`: endpoints FastAPI
- `scripts/`: instaladores y utilidades
  - Windows:
    - `install-windows.cmd` / `install-windows.ps1` / `install-windows-full.ps1`
    - `uninstall-windows.cmd` / `uninstall-windows.ps1`
    - `nodo-api-windows-install.ps1` (autostart)
    - `start-nodo-api.ps1`, `nodo-api-status.ps1`
    - `wg-resume-windows-install.ps1`, `wg-resume-windows.ps1`
  - Linux:
    - `install-linux.sh`
  - DB:
    - `mysql_schema.sql`

---

## Requisitos

### Windows

- PowerShell
- Internet (si hay que instalar Python automáticamente)
- WireGuard for Windows (solo si se provisiona `wg0.conf`)
- MySQL:
  - En Docker (opcional): contenedor `mysql56-app` (dev)
  - O MySQL local/remoto: credenciales en `.env` y permisos `CREATE TRIGGER`/`DROP TRIGGER`

### Linux

- `python3`
- `bash`
- WireGuard (`wg`, `wg-quick`) opcional
- Docker opcional
- Para MySQL fuera de Docker: `mysql` client instalado

---

## Configuración (env.txt/.env)

Este servicio soporta configuración desde:

- `env.txt` (**preferido** en el bundle de provisioning)
- `.env` (fallback para compatibilidad)

En local, puedes usar cualquiera. Si quieres ejecutar exportando variables en tu shell, recuerda que **valores con espacios deben ir entre comillas**, por ejemplo:

```env
NODO_NOMBRE="Tienda Ejemplo"
```

### `env.txt` mínimo recomendado (dev / fork-router)

```env
# Identidad del nodo
NODO_ID=tienda-ejemplo-01
NODO_NOMBRE="Tienda Ejemplo"
NODO_ROLE=slave

# Token que debe enviar el orquestador Nest (Authorization: Bearer)
NODO_API_TOKEN=cambiar-token-secreto

# API HTTP(S)
NODO_HOST=0.0.0.0
NODO_PORT=8443

# Dev: permitir HTTP sin TLS
NODO_ALLOW_INSECURE=true

# TLS (opcional)
NODO_SSL_CERTFILE=
NODO_SSL_KEYFILE=

# Features fuera de alcance (fork-router)
SYNC_WORKER_ENABLED=false
HUB_PULL_ENABLED=false
HUB_PUSH_ENABLED=false
HUEY_ENABLED=false

# MySQL del nodo (dev con Docker)
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=multishop
MYSQL_DATABASE=mi_base_historica
```

### Variables más comunes

- MySQL del nodo:
  - `MYSQL_HOST`
  - `MYSQL_PORT`
  - `MYSQL_USER`
  - `MYSQL_PASSWORD`
  - `MYSQL_DATABASE`
- API:
  - `NODO_HOST`
  - `NODO_PORT`
  - `NODO_ALLOW_INSECURE` / `NODO_SSL_CERTFILE` / `NODO_SSL_KEYFILE`
 - Auth:
  - `NODO_API_TOKEN`

---

## Instalación

La instalación asume que el usuario recibe **todo el proyecto** y opcionalmente un bundle de provisioning con:

- `env.txt`
- `wg0.conf` (si aplica WireGuard)

### Windows (modo pro)

Recomendado: ejecutar como **Administrador**.

1. Ir a `Multishop-nodo-API/scripts/`.
2. Clic derecho `install-windows.cmd` -> **Ejecutar como administrador**.
3. El instalador:
   - verifica/instala Python 3.10+ (automático vía `winget` si falta)
   - crea `venv` e instala `requirements.txt`
   - configura `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` (scripts del venv)
   - WireGuard (opcional): si hay `wg0.conf`, instala/levanta túnel como servicio
   - valida MySQL local/remoto usando `MYSQL_*` del `env.txt`/`.env`
   - registra autostart de la API (tareas programadas + carpeta Inicio)

Desinstalación:

- `scripts/uninstall-windows.cmd` (Ejecutar como administrador)

Verificar sintaxis PowerShell (antes de instalar en tienda):

```powershell
cd scripts
powershell -NoProfile -ExecutionPolicy Bypass -File .\test-ps-syntax.ps1
```

Opcional (más reglas de estilo): módulo [PSScriptAnalyzer](https://github.com/PowerShell/PSScriptAnalyzer) — `Install-Module PSScriptAnalyzer` y `Invoke-ScriptAnalyzer -Path .\install-windows-full.ps1`.

### Linux

1. En `Multishop-nodo-API/scripts/`:

```bash
./install-linux.sh <BUNDLE_DIR>
```

2. El instalador:
   - WireGuard (opcional): levanta `wg0` si existe `wg0.conf` y `wg` está instalado
   - copia `env.txt` si existe
   - valida MySQL local/remoto con `mysql` usando `MYSQL_*` del `env.txt`/`.env`
   - crea `venv` e instala dependencias

---

## Ejecución

### Arrancar API

- Windows:

```powershell
.\venv\Scripts\python main.py
```

- Linux:

```bash
./venv/bin/python main.py
```

## Notas sobre WireGuard vs red normal

Regla práctica:

- `.env` + `wg0.conf`: el nodo queda listo para comunicarse con el hub por **VPN**.
- solo `.env`: el nodo opera por **red normal**.

---

## Verificación y troubleshooting

### Ver estado (Windows)

- `scripts/nodo-api-status.ps1`

Logs (Windows) normalmente en:

- `C:\ProgramData\Multishop\`
  - `nodo-api-start.log`
  - `nodo-api.out.log`
  - `nodo-api.err.log`

### Health

```bash
curl http://127.0.0.1:<NODO_PORT>/api/health

# Si tu endpoint requiere Bearer (según configuración del nodo/hub):
curl http://127.0.0.1:<NODO_PORT>/api/health -H "Authorization: Bearer <NODO_API_TOKEN>"
```

### La API se cierra al recibir requests no esperados (Windows)

Este fork expone únicamente las rutas descritas arriba. Si ves referencias a rutas distintas, verifica que estés ejecutando este repositorio y no una variante anterior.

---

## Seguridad

- No subas `.env` a git.
- No subas `wg0.conf` a git.
- Los tokens (Bearer) y API keys deben provisionarse por canal seguro.

---

## Referencias

- Documentación principal: `doc/doc.md`
- Instaladores: `scripts/`
