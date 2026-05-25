# Multishop Nodo API

Nodo local de Multishop (FastAPI/Python) para operar con una **BD MySQL local** y sincronizarse con el **Hub/Orquestador**.

Este proyecto implementa un modelo híbrido:

- **Sync entrante (Hub -> Nodo)**: cola FIFO persistente (SQLite) para aplicar eventos en orden y con idempotencia.
- **CDC / Sync saliente (Nodo -> Hub)**: patrón **Outbox** en MySQL + **triggers** para registrar cambios locales y enviarlos al hub.
- **Envío resiliente (opcional)**: **Huey** con backend SQLite para reintentos persistentes cuando haya fallas de conectividad.
- **Conectividad (opcional)**: WireGuard (VPN) o red normal, dependiendo del provisioning.

La guía completa y detallada está en:

- `doc/doc.md`

---

## Tabla de contenido

- [Características](#características)
- [Arquitectura (resumen)](#arquitectura-resumen)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Requisitos](#requisitos)
- [Configuración (.env)](#configuración-env)
- [Instalación](#instalación)
  - [Windows (modo pro)](#windows-modo-pro)
  - [Linux](#linux)
- [Ejecución](#ejecución)
  - [Arrancar API](#arrancar-api)
  - [Huey consumer (opcional, recomendado)](#huey-consumer-opcional-recomendado)
- [Triggers / Outbox (CDC)](#triggers--outbox-cdc)
- [Notas sobre WireGuard vs red normal](#notas-sobre-wireguard-vs-red-normal)
- [Verificación y troubleshooting](#verificación-y-troubleshooting)
- [Seguridad](#seguridad)

---

## Características

- Sync entrante persistente (FIFO) para aplicar eventos del hub sin perder orden.
- Outbox + triggers en MySQL para detectar cambios en tablas clave.
- Envío de outbox al hub en batches.
- Huey opcional para reintentos persistentes de envío (ideal si la conectividad es intermitente).
- Instaladores para Windows y Linux.

---

## Arquitectura (resumen)

### 1) Hub -> Nodo (push)

- Endpoint del nodo: `POST /api/sync/events`
- El nodo encola eventos en SQLite (persistente) y los aplica en orden por `sequence`.

Componentes:

- `sync_store.py` (SQLite)
- `sync_worker.py`
- `sync_apply.py`
- `routes/sync.py`

### 2) Nodo -> Hub (CDC / push)

- Triggers en MySQL generan filas en `sync_outbox` ante cambios en tablas monitoreadas.
- Un worker drena `sync_outbox` y envía eventos al hub.

Componentes:

- `scripts/mysql_outbox_triggers.sql`
- `outbox_mysql.py`
- `outbox_worker.py`
- `hub_client.py`

### 3) Envío resiliente con Huey (opcional)

- Huey reserva eventos `pending -> processing`.
- Si el envío falla, repone a `pending` e incrementa `attempts`.
- Un scheduler auto-programa el enqueue cada `HUEY_OUTBOX_ENQUEUE_INTERVAL_SECONDS`.

Componentes:

- `huey_app.py`
- `huey_tasks.py`

---

## Estructura del proyecto

- `main.py`: entry point de la API
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
    - `mysql_outbox_triggers.sql`

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

## Configuración (.env)

- Copia `.env.example` a `.env` y ajusta valores.
- Variables relevantes:
  - Hub:
    - `HUB_BASE_URL`
    - `HUB_PUSH_PATH`
    - `HUB_API_KEY` (si aplica)
  - MySQL del nodo:
    - `MYSQL_HOST`
    - `MYSQL_PORT`
    - `MYSQL_USER`
    - `MYSQL_PASSWORD`
    - `MYSQL_DATABASE`
  - Flags:
    - `HUB_PUSH_ENABLED` (usa outbox)
    - `SYNC_WORKER_ENABLED`
    - `HUEY_ENABLED` (recomendado para reintentos persistentes)

---

## Instalación

La instalación asume que el usuario recibe **todo el proyecto** y opcionalmente un bundle de provisioning con:

- `.env`
- `wg0.conf` (si aplica WireGuard)

### Windows (modo pro)

Recomendado: ejecutar como **Administrador**.

1. Ir a `Multishop-nodo-API/scripts/`.
2. Clic derecho `install-windows.cmd` -> **Ejecutar como administrador**.
3. El instalador:
   - verifica/instala Python 3.10+ (automático vía `winget` si falta)
   - crea `venv` e instala `requirements.txt`
   - WireGuard (opcional): si hay `wg0.conf`, instala/levanta túnel como servicio
   - triggers/outbox:
     - primero intenta Docker (`mysql56-app`)
     - si no, intenta MySQL local/remoto usando `MYSQL_*` del `.env`
   - registra autostart de la API (tareas programadas + carpeta Inicio)

Desinstalación:

- `scripts/uninstall-windows.cmd` (Ejecutar como administrador)

### Linux

1. En `Multishop-nodo-API/scripts/`:

```bash
./install-linux.sh <BUNDLE_DIR>
```

2. El instalador:
   - WireGuard (opcional): levanta `wg0` si existe `wg0.conf` y `wg` está instalado
   - copia `.env` si existe
   - triggers/outbox:
     - intenta Docker si existe `mysql56-app`
     - si no, intenta MySQL local/remoto con `mysql` usando `MYSQL_*` del `.env`
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

### Huey consumer (opcional, recomendado)

Huey corre en un proceso separado a la API.

- Windows:

```powershell
.\venv\Scripts\python -m huey.bin.huey_consumer huey_tasks.huey
```

- Linux:

```bash
./venv/bin/python -m huey.bin.huey_consumer huey_tasks.huey
```

---

## Triggers / Outbox (CDC)

El archivo `scripts/mysql_outbox_triggers.sql`:

- crea la tabla `sync_outbox`
- instala triggers en tablas monitoreadas (inventario, proveedores y transaccional)

Notas:

- Para MySQL local/remoto, el usuario de MySQL debe poder crear triggers.
- En Windows el instalador valida conectividad antes de aplicar el SQL.

---

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
curl http://127.0.0.1:8443/api/health -H "Authorization: Bearer <TOKEN>"
```

### Si fallan triggers/outbox

- Verifica `.env`:
  - `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`
- Verifica permisos MySQL:
  - `CREATE TRIGGER`, `DROP TRIGGER`, `CREATE`
- Si tu MySQL es local/remoto y estás en Linux, asegúrate de tener `mysql` client instalado.

---

## Seguridad

- No subas `.env` a git.
- No subas `wg0.conf` a git.
- Los tokens (Bearer) y API keys deben provisionarse por canal seguro.

---

## Referencias

- Documentación principal: `doc/doc.md`
- Instaladores: `scripts/`
