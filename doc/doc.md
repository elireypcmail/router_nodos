# Estado del proyecto (nodos) — Implementaciones realizadas

Este documento resume lo implementado hasta el momento en el proyecto de **nodos locales** (FastAPI/Python) dentro de `Multishop-nodo-API/`, incluyendo sincronización híbrida y detección de cambios en BD local mediante outbox + triggers.

## 1) DB local (Docker)

- **Contenedor**: `mysql56-app`
- **Motor**: MySQL 5.6
- **DB con datos/tablas**: `mi_base_restaurada`
- **Nota**: `mi_base_historica` existe, pero en el entorno actual está vacía (0 tablas). Toda verificación y scripts apuntan a `mi_base_restaurada`.

## 2) Nodo (FastAPI) — base

- Proyecto: `Multishop-nodo-API/`
- Entry point: `main.py`
- Auth: Bearer token (middleware existente)
- TLS: soportado vía `NODO_SSL_CERTFILE` / `NODO_SSL_KEYFILE`; modo HTTP solo dev con `NODO_ALLOW_INSECURE=true`.

## 2.1) Provisioning de conectividad (WireGuard vs red normal)

Para que el nodo pueda hacer **pull** y/o **push** hacia el hub se usan (opcionalmente) dos archivos en el bundle de provisioning:

- `.env`:
  - Configura URLs/credenciales del hub y la BD MySQL local del nodo.
  - Sin `.env`, el nodo puede arrancar, pero el cliente `HubClient` no podrá operar (no hay `HUB_BASE_URL`) y el sync/push quedará deshabilitado o fallará.

- `wg0.conf`:
  - Configura WireGuard (VPN).
  - Si se incluye y WireGuard está disponible en el sistema, el nodo puede comunicarse con el hub **por VPN**.
  - Si no se incluye, el nodo se comunica con el hub **por red normal**.

Regla práctica (identificación):
- Si entregas **`.env` + `wg0.conf`**: el nodo queda listo para operar contra el hub **por WireGuard**.
- Si entregas **solo `.env`**: el nodo opera contra el hub **por red normal**.
- Si entregas **solo `wg0.conf`**: puede levantarse VPN, pero faltará configuración del hub (no hay sync).
- Si no entregas ninguno: instalación mínima (sin VPN y sin sync).

## 3) Sync entrante (Hub -> Nodo) con FIFO persistente

Se implementó una cola FIFO persistente en SQLite para aplicar eventos en orden:

- **Archivo**: `sync/store.py`
  - `sync_state.last_applied_sequence`
  - cola `sync_queue` con estados `pending/processing/done/failed`
  - idempotencia por `event_id` único

- **Archivo**: `sync/worker.py`
  - worker async: toma `pending` ordenados por `sequence`, aplica y marca `done`/`failed`.

- **Aplicación (MySQL local)**:
  - **Archivo**: `sync/apply.py`
  - **Cliente MySQL**: `db/mysql.py`
  - Implementación inicial: `entity="categorias"` (upsert/delete en `catego`).

- **Rutas**:
  - **Archivo**: `routes/sync.py`
  - `POST /api/sync/apply`: encola eventos idempotentes
  - `GET /api/sync/status`: estado del worker/cola + last_applied_sequence

## 4) CDC / Sync saliente (Nodo -> Orquestador) por Outbox + Triggers (inventario/proveedores/compras/ventas/factura/kardex)

Requisito: el nodo debe **enviar eventos** al orquestador cuando se muevan (INSERT/UPDATE/DELETE) las tablas:

- `sinv` (inventario)
- `sprv` (proveedores)
- `ventas` / `ventasd`
- `factura` / `facturad`
- `kardex` / `kardexd`
- `comprasdbf`

### 4.1 Outbox en MySQL

- **Repositorio**: `outbox/mysql.py`
  - `sync_outbox` con `status=pending|sent|failed`
  - `fetch_pending()`, `mark_sent()`, `mark_failed()`, `stats()`, `recent()`

### 4.2 Worker de envío

- **Archivo**: `outbox/worker.py`
  - drena `sync_outbox` (`pending`) en batches y envía al hub.

### 4.3 Cliente hub

- **Archivo**: `hub/client.py`
  - POST hacia `HUB_BASE_URL + HUB_PUSH_PATH`
  - header `x-internal-api-key: HUB_API_KEY` (si está configurado)

### 4.4 SQL de triggers

- **Archivo**: `scripts/mysql_outbox_triggers.sql`
  - Crea `sync_outbox` si no existe
  - Instala triggers AFTER INSERT/UPDATE/DELETE para:
    - `sinv` usando `id_inv + codigo`
    - `sprv` usando `id_sprv + cod_prv`
    - `kardex` y `kardexd` usando PK real `indice`
    - `ventas` usando clave natural `numero` (tabla no tiene PK)
    - `ventasd` usando `numero + codigo + indice_det`
    - `factura` usando `numero + codigo`
    - `facturad` usando `numero + codigo`
    - `comprasdbf` usando `contador + numdoc + codigo + fecha`

### 4.5 Activación en el nodo

- En `main.py`:
  - si `HUB_PUSH_ENABLED=true`, inicializa `OutboxRepository`, crea el schema (`ensure_schema`) e inicia `OutboxWorker`.

## 5) Endpoint de monitoreo outbox

- **Ruta**: `GET /api/sync/outbox/status`
  - stats (pending/sent/failed)
  - últimos `pending` y `failed`

> Este endpoint requiere que el nodo inicialice `outbox_repo` (actualmente sucede cuando `HUB_PUSH_ENABLED=true`).

## 5.2 Envío resiliente al hub con Huey (cola persistente)

Para garantizar que si falla la conectividad con el orquestador/hub los envíos queden en cola y se reintenten, se integró Huey con backend SQLite.

- Config:
  - `HUEY_ENABLED=true`
  - `HUEY_DB_PATH=./data/huey.sqlite`

Comportamiento:
- La tarea Huey reserva registros de `sync_outbox` (`pending` → `processing`) y envía batch al hub.
- Si falla el envío, los IDs se devuelven a `pending` (incrementa `attempts`) y Huey reintenta.
- El enqueue se auto-programa cada `HUEY_OUTBOX_ENQUEUE_INTERVAL_SECONDS`.

Ejecución del consumer Huey:

Huey debe correr en un proceso separado a la API.

- Linux/mac:

```bash
./venv/bin/python -m huey.bin.huey_consumer huey_tasks.huey
```

- Windows:

```powershell
.\venv\Scripts\python -m huey.bin.huey_consumer huey_tasks.huey
```

## 5.1 CRUD local de categorías (Opción B)

Para operación local/offline, el nodo expone endpoints para crear/editar/eliminar categorías en `catego`. Estos cambios generan eventos en `sync_outbox` mediante triggers (para que el orquestador pueda enterarse cuando tenga receptor).

- **Router**: `routes/categorias.py`
- **Endpoints**:
  - `GET /api/categorias?search=&limit=`
  - `GET /api/categorias/{ccate}`
  - `POST /api/categorias` (upsert)
  - `DELETE /api/categorias/{ccate}`

Triggers adicionales:
- En `scripts/mysql_outbox_triggers.sql` se agregaron triggers `trg_catego_ai/au/ad` para encolar cambios en `sync_outbox`.

## 6) Variables de entorno agregadas

En `Multishop-nodo-API/core/config.py` (o shim `config.py`) y `.env.example`:

- Rol:
  - `NODO_ROLE=slave|master`

- Sync FIFO (SQLite):
  - `SYNC_DB_PATH=./data/sync.sqlite`
  - `SYNC_WORKER_ENABLED=true`
  - `SYNC_WORKER_POLL_INTERVAL_SECONDS=0.5`

- Hub (pull) — pendiente de implementar:
  - `HUB_PULL_ENABLED`
  - `HUB_PULL_INTERVAL_SECONDS`
  - `HUB_PULL_PATH`
  - `HUB_PULL_BATCH_SIZE`

- Hub (push / outbox):
  - `HUB_PUSH_ENABLED=false`
  - `HUB_PUSH_INTERVAL_SECONDS=1`
  - `HUB_PUSH_PATH=/orchestration/node-outbox`

- MySQL local del nodo:
  - `MYSQL_HOST`
  - `MYSQL_PORT`
  - `MYSQL_USER`
  - `MYSQL_PASSWORD`
  - `MYSQL_DATABASE` (en dev: `mi_base_restaurada`)

## 7) Verificación (Docker)

### 7.1 Ver triggers instalados

```bash
docker exec -i mysql56-app mysql -u root -pmultishop -D mi_base_restaurada -e "\
SELECT trigger_name, event_manipulation, event_object_table \
FROM information_schema.triggers \
WHERE trigger_schema=DATABASE() \
  AND event_object_table IN ('sinv','sprv','ventas','ventasd','factura','facturad','kardex','kardexd','comprasdbf') \
ORDER BY event_object_table, trigger_name;"
```

### 7.2 Ver outbox crecer

```bash
docker exec -i mysql56-app mysql -u root -pmultishop -D mi_base_restaurada -e "\
SELECT id, table_name, op, created_at, status \
FROM sync_outbox \
ORDER BY id DESC \
LIMIT 20;"
```

## 8) Pendientes inmediatos del nodo

- Implementar `GET /api/inventario` real usando `sinv` (reemplazar stub)
- Definir y documentar qué campos exactos se retornan en inventario y cómo se busca
- Asegurar que cambios de DB (tablas, triggers, índices, outbox, etc.) se desplieguen siempre mediante scripts de instalación/upgrade para nodos locales.

## 9) Pull / Catch-up (Nodo -> Hub) — contrato esperado

El nodo puede ponerse al día consultando al hub por eventos a partir del último `last_applied_sequence`.

- **Feature flag**: `HUB_PULL_ENABLED=true`
- **Worker**: `sync/pull_worker.py` (`HubPullWorker`)
- **Frecuencia**: `HUB_PULL_INTERVAL_SECONDS`
- **Batch**: `HUB_PULL_BATCH_SIZE`

### 9.1 Endpoint esperado en hub

El nodo hará `GET` a:

- `HUB_BASE_URL + HUB_PULL_PATH`

Con query params:

- `from` (int) = último `sequence` aplicado + 1
- `limit` (int)
- `nodo_id` (string)

Headers:

- `x-internal-api-key: HUB_API_KEY` (si está configurado)

### 9.2 Respuesta esperada

El hub debe devolver una de estas dos formas:

1) Objeto:

```json
{ "events": [ {"event_id":"...","sequence":1,"entity":"...","action":"upsert","payload":{},"created_at":"..."} ] }
```

2) Lista directa:

```json
[ {"event_id":"...","sequence":1,"entity":"...","action":"upsert","payload":{},"created_at":"..."} ]
```

## 10) Compatibilidad con proyectos guía (multishop-hub / nodo)

Para acoplarse a los contratos de `multishop-hub` y `nodo` (referencia, no editables), el nodo implementa:

- `POST /api/sync/events` (hub → nodo)
  - Body (categorías): `{ "entity_type": "inventory_category", "payload": { ... } }`
  - Body (proveedores): `{ "entity_type": "sprv", "payload": { "action": "upsert|delete", "row": { ... } } }`
  - Body (inventario): `{ "entity_type": "sinv", "payload": { "action": "upsert|delete", "row": { ... } } }`
  - Nota: transaccional (compras/ventas/kardex) no se aplica por este endpoint; debe entrar por pull desde `/orchestration/sync/events`.

- `POST /api/sync/categorias` (legacy)
  - Alias hacia `/api/sync/events` con `entity_type=inventory_category`

- `POST /api/sync/categorias/pull`
  - El hub pide al nodo que ejecute el pull paginado al hub usando:
    - `GET <HUB_BASE_URL>/api/nodo/sync/categorias?page=1&limit=100`

- `GET /api/proveedores?search=...`
  - Consulta local a `sprv` (BD MySQL del nodo)

Además, cuando se hace `POST /api/categorias` (CRUD local), si `HUB_BASE_URL` está configurado el nodo intenta reportar al hub en:

- `POST <HUB_BASE_URL>/api/nodo/categorias`

Autenticación (guía):

- `Authorization: Bearer <NODO_API_TOKEN>`

---

## 11) Instalación del nodo (paso a paso) — Windows y Linux

Esta sección describe **qué hace el instalador**, qué requiere, y el **paso a paso** para usuarios finales.

### 11.1 Qué instala/configura el instalador

- **Python y dependencias**:
  - Se crea un entorno virtual (`venv`) dentro del proyecto del nodo.
  - Se instalan dependencias de `requirements.txt` dentro del `venv`.
  - En Windows el instalador intenta asegurar automáticamente **Python 3.10+** (usa `winget` si falta).

- **WireGuard (opcional)**:
  - Si existe `wg0.conf` en el bundle y WireGuard está disponible, se configura VPN.
  - Si no existe `wg0.conf`, el nodo opera por **red normal**.

- **Triggers/outbox (CDC)**:
  - Se intenta activar `scripts/mysql_outbox_triggers.sql`.
  - Si hay MySQL en Docker (contenedor `mysql56-app`), se aplica dentro del contenedor.
  - Si no hay Docker/contendor, se aplica contra MySQL **local/remoto** usando `MYSQL_*` del `.env`.

- **Arranque automático (Windows)**:
  - En Windows (modo “pro”) el instalador registra autostart usando tareas programadas y carpeta Inicio.
  - Si se ejecuta como Administrador, también registra tarea de “resume” de WireGuard.

### 11.2 Requisitos previos

#### Windows

- Ejecutar instalación como **Administrador** (recomendado para:
  - instalar/levantar WireGuard como servicio
  - crear tareas programadas de autostart y de VPN resume)
- Conectividad a internet para instalar Python vía `winget` (si no está instalado).
- WireGuard for Windows (si se entregará `wg0.conf`).
- Si MySQL está fuera de Docker:
  - el usuario de MySQL debe tener permisos de `CREATE TRIGGER`, `DROP TRIGGER`, y `CREATE`.

#### Linux

- `python3` instalado.
- `docker` opcional (solo si la DB está en contenedor `mysql56-app`).
- WireGuard (`wg`, `wg-quick`) opcional.
- Si MySQL está fuera de Docker:
  - tener el cliente `mysql` instalado (mysql-client)
  - permisos de `CREATE TRIGGER`, `DROP TRIGGER`, y `CREATE`.

### 11.3 Contenido del bundle de provisioning

El paquete de instalación que recibe el usuario incluye **todo el proyecto del nodo**.

Además, puede incluir opcionalmente:

- `.env` (recomendado): configuración del hub y credenciales MySQL del nodo.
- `wg0.conf` (opcional): configura WireGuard para operar contra el hub por VPN.

Regla práctica:

- `.env` + `wg0.conf` = operación contra hub por **WireGuard**.
- solo `.env` = operación por **red normal**.

### 11.4 Instalación en Windows (modo admin / no admin)

#### Opción recomendada (Administrador)

1. Abrir la carpeta del proyecto y entrar a `Multishop-nodo-API/scripts/`.
2. Clic derecho en `install-windows.cmd` → **Ejecutar como administrador**.
3. El instalador:
   - si falta Python 3.10+, intenta instalarlo automáticamente
   - crea `venv` e instala dependencias
   - si hay `wg0.conf`, instala/levanta el túnel WireGuard como servicio
   - activa triggers/outbox (Docker si existe, o MySQL local/remoto si `MYSQL_*` está en `.env`)
   - registra autostart de la API (tareas programadas + carpeta Inicio)

Verificación:

- Estado/Logs: `scripts/nodo-api-status.ps1`
- Health: `curl http://127.0.0.1:8443/api/health -H "Authorization: Bearer <TOKEN>"`

Huey (opcional):

```powershell
.\venv\Scripts\python -m huey.bin.huey_consumer huey_tasks.huey
```

#### Sin Administrador

1. Ejecuta `install-windows.ps1` en PowerShell normal.
2. El instalador:
   - puede preparar `.env` y `venv`
   - si hay `wg0.conf`, pedirá importar manualmente el túnel en WireGuard GUI
   - puede no poder registrar tareas programadas/autostart

Si necesitas el modo completo, repite como Administrador.

#### Desinstalación (Windows)

- Clic derecho → **Ejecutar como administrador**:
  - `scripts/uninstall-windows.cmd`

### 11.5 Instalación en Linux

1. Abrir terminal en `Multishop-nodo-API/scripts/`.
2. Ejecutar:

```bash
./install-linux.sh <BUNDLE_DIR>
```

Comportamiento:

- Si existe `wg0.conf` y está instalado WireGuard, intenta levantar `wg0`.
- Copia `.env` si existe.
- Triggers/outbox:
  - Si existe Docker y contenedor `mysql56-app`, aplica SQL dentro del contenedor.
  - Si no, intenta aplicar a MySQL local/remoto con `mysql` usando `MYSQL_*` del `.env`.
- Crea `venv` e instala dependencias.

Arranque API:

```bash
./venv/bin/python main.py
```

Huey (opcional):

```bash
./venv/bin/python -m huey.bin.huey_consumer huey_tasks.huey
```
