# Desarrollo nodo en macOS

Script único para levantar el entorno local del agente **Multishop-nodo-API** en el Mac (MySQL en Docker, triggers, VPN opcional, API en primer plano con logs).

## Requisitos

| Herramienta | Instalación |
|-------------|-------------|
| Docker Desktop | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Python 3.11+ | `brew install python@3.12` |
| WireGuard (opcional) | `brew install wireguard-tools` o app [WireGuard](https://apps.apple.com/app/wireguard/id1451685025) |

Archivo `.env` en `Multishop-nodo-API/` con al menos:

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=multishop
MYSQL_PASSWORD=multishop
MYSQL_DATABASE=mi_base_historica
ROUTER_EVENTS_URL=http://localhost:3000
HUEY_ENABLED=true
NODO_ID=...
ROUTER_INTERNAL_API_KEY=...
```

La base debe existir (importar dump en el volumen Docker). Credenciales por defecto del compose: usuario `multishop` / BD `mi_base_historica` (ver `docker-compose.mysql.yml` en la raíz del monorepo).

## Instalación (provisioning)

Para copiar `.env` del bundle, crear venv, aplicar triggers de movimientos y registrar Huey en LaunchAgent:

```bash
chmod +x scripts/mac/install-mac.sh scripts/mac/install-huey-launchd.sh
./scripts/mac/install-mac.sh ~/Downloads/mi-tienda-bundle
```

Requiere `HUEY_ENABLED=true` y `ROUTER_EVENTS_URL` en `.env` para activar outbox y el consumer.

## Desarrollo (`./start-dev.sh` en la raíz del nodo)

```bash
cd router_nodos   # raíz del agente
chmod +x start-dev.sh
./start-dev.sh
```

Con bundle de provisioning (copia `.env` y usa `wg0.conf` del bundle):

```bash
./start-dev.sh --bundle-dir ~/Downloads/mi-tienda-bundle
```

(`start-dev.sh` delega en `scripts/mac/start-dev.sh`; también existe `start-dev-quick.sh` con `--skip-venv`.)

### Qué hace el script

1. Comprueba Python y crea/actualiza `venv` + `pip install -r requirements.txt`
2. `docker compose -f ../../docker-compose.mysql.yml up -d` (contenedor `multishop-mysql-tienda`)
3. Espera a que MySQL responda
4. Si `HUEY_ENABLED=true` o hay `ROUTER_EVENTS_URL`, aplica `mysql_outbox_triggers_movimientos.sql` vía `apply_mysql_outbox_triggers.py`
5. Si encuentra `wg0.conf` (nodo, `vpn/`, bundle o `nodo/wg0.conf` del repo), intenta `sudo wg-quick up` (pide contraseña de Mac)
6. Arranca `python main.py` en primer plano (logs en la misma terminal)

### Opciones

| Flag | Efecto |
|------|--------|
| `--bundle-dir DIR` | Copia `.env` del bundle; busca `wg0.conf` ahí |
| `--no-wg` | No toca WireGuard |
| `--skip-triggers` | No aplica outbox |

Cada arranque con triggers ejecuta `apply_mysql_outbox_triggers.py`: **borra solo los `trg_router_*` y `ms_router_json_*` del manifiesto**, luego reinstala. No toca `sync_outbox` ni triggers del hub.

| `--skip-docker` | No levanta Docker; usa MySQL ya corriendo según `.env` |

Los triggers del ERP (p. ej. `fechaua_i` en `sinv`) **no se eliminan**; solo los de Multishop listados en `mysql_outbox_triggers.sql`.
| `--recreate-venv` | Borra y recrea `venv` |

## WireGuard

Orden de búsqueda de `wg0.conf`:

1. `--bundle-dir/wg0.conf` o `vpn/wg0.conf`
2. `Multishop-nodo-API/wg0.conf` o `vpn/wg0.conf`
3. `nodo-servidor/nodo/wg0.conf`

Sin `.conf`: la API usa red normal (`HUB_BASE_URL` debe ser alcanzable, p. ej. `http://localhost:3000`).

Con VPN al hub de dev: `HUB_BASE_URL=http://10.66.0.1:3000` en `.env`.

Al salir con Ctrl+C, el script baja el túnel si lo había levantado él.

## Huey (outbox movimientos → webhooks)

Con `HUEY_ENABLED=true` en `.env`, `start-dev.sh` arranca el consumer Huey en background junto con la API.

Instalación persistente (LaunchAgent del usuario):

```bash
./scripts/mac/install-huey-launchd.sh
```

En **otra terminal** (solo si no usas `start-dev.sh` ni LaunchAgent):

```bash
cd Multishop-nodo-API
source venv/bin/activate
python -m huey.bin.huey_consumer huey_tasks.huey
```

Sin Huey (`HUEY_ENABLED=false`), la API puede usar el forwarder asyncio en `main.py` si `ROUTER_EVENTS_URL` está configurada.

## Simulaciones transaccionales

Tras arrancar, en otra terminal:

```bash
source venv/bin/activate
python scripts/test/simulate_compra.py --flush
```

Ver `scripts/test/README.md`.

## Problemas frecuentes

- **Docker no corre** → abrir Docker Desktop.
- **Base vacía** → importar dump (ver comentarios en `docker-compose.mysql.yml`).
- **Triggers fallan** / `JSON_OBJECT does not exist` → la BD es MySQL 5.6; reaplica el SQL actualizado:  
  `MS_MYSQL_*=... MS_SQL_FILE=scripts/mysql_outbox_triggers.sql python scripts/apply_mysql_outbox_triggers.py`
- **Error tras cambiar triggers** → vuelve a ejecutar `start-dev.sh` o el `apply_mysql_outbox_triggers.py` de arriba.
- **wg-quick pide sudo** → normal en Mac; o activa el túnel desde la app WireGuard y usa `--no-wg`.
