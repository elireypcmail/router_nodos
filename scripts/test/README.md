# Simulaciones transaccionales (MySQL → outbox → hub)

## Tres nodos en Docker

Para levantar **3 tiendas** con `backup_seguro.sql.gz` en cada MySQL: [README-docker-nodos.md](./README-docker-nodos.md).

Scripts que insertan en las tablas del ERP local para disparar los triggers de `sync_outbox` y el flujo hacia el hub.

**Importante:** los triggers de outbox **no** actualizan `sinv`. Por defecto `simulate_compra.py` también hace `UPDATE sinv` de **existencia** y **costo/costopro** (CPP con `--precio`, misma lógica que el hub). Sin eso, el hub puede recibir el evento por `--flush`, pero **Sync existencia** en el portal lee `sinv` en la tienda y verá stock/costos viejos. Usa `--no-update-sinv` solo si quieres probar únicamente el outbox.

`simulate_compra.py` además hace UPSERT en `detalle` (lote default, cubica `01`) para encolar `inventory_lot` y poblar lotes unificados en el hub. Requiere triggers `trg_detalle_*` en MySQL.

Con `--lotes N` crea **N** filas en `detalle` y reparte la cantidad de la compra entre ellas (`N` no puede ser mayor que `--cantidad`). Sin `--lotes-pct` reparte en partes iguales; con `--lotes-pct 50,30,20` usa esos porcentajes (deben coincidir con `N`).

## Requisitos

1. `.env` en `Multishop-nodo-API/` con `MYSQL_*` apuntando a la base de la tienda.
2. Tabla `sync_outbox` y triggers (MySQL **5.6**; el instalador **siempre** hace DROP + CREATE):

   ```bash
   cd Multishop-nodo-API
   source venv/bin/activate
   export MS_MYSQL_HOST=localhost MS_MYSQL_PORT=3306
   export MS_MYSQL_USER=multishop MS_MYSQL_PASSWORD=multishop
   export MS_MYSQL_DATABASE=mi_base_historica
   export MS_SQL_FILE="$(pwd)/scripts/mysql_outbox_triggers.sql"
   python scripts/apply_mysql_outbox_triggers.py
   ```

   Tras cambiar `mysql_outbox_triggers.sql`, vuelve a ejecutar ese comando (o `./scripts/mac/start-dev.sh`).

3. Al menos un producto en `sinv` (o pasar `--codigo SKU`).
4. Para enviar al hub sin levantar la API: `HUB_BASE_URL` y `HUB_API_KEY` en `.env` y flag `--flush`.

Con la API en marcha y `HUB_PUSH_ENABLED=true`, el `OutboxWorker` envía los `pending` automáticamente (no hace falta `--flush`).

## Scripts

| Script | Tabla | Evento hub |
|--------|-------|------------|
| `simulate_compra.py` | `comprasdbf` | `purchase` |
| `simulate_venta.py` | `ventasi` | `sale` |
| `simulate_kardex_devolucion.py` | `kardex` | `kardex` (`--tipo devov` o `devoc`) |
| `simulate_kardex_ajuste.py` | `kardex` | `kardex` (`--direccion entrada` o `salida`) |

## Uso

Usa el venv del proyecto. El `.env` se lee siempre desde la **raíz de Multishop-nodo-API** (no importa desde qué carpeta ejecutes).

Desde la raíz del nodo:

```bash
cd Multishop-nodo-API
source venv/bin/activate
python scripts/test/simulate_compra.py
python scripts/test/simulate_venta.py --cantidad 2
```

Desde `scripts/test/` (también válido):

```bash
cd Multishop-nodo-API/scripts/test
python simulate_venta.py --cantidad 2
python simulate_kardex_devolucion.py --tipo devov
python simulate_kardex_ajuste.py --direccion entrada
python run_all.py --codigo ART001 --flush
```

No uses `python scripts/test/...` estando ya dentro de `scripts/test` (duplica la ruta).

Opciones comunes (todos los scripts):

- `--codigo` — SKU; si se omite, primer registro de `sinv`
- `--aleatorio` — producto al azar de `sinv` (no usar con `--codigo`)
- `--cantidad` — cantidad del movimiento (default 1)
- `--dry-run` — no inserta, solo imprime el plan
- `--flush` — envía batch `pending` a `POST /api/nodo/events/batch`
- `--no-update-sinv` — no toca `sinv.existencia` (solo movimiento + outbox)

Solo `simulate_compra.py`:

- `--lotes N` — N lotes en `detalle` (requiere `N <= --cantidad`)
- `--lotes-pct P1,P2,...` — reparto por % (misma cantidad de valores que `--lotes`)

Ejemplos:

```bash
python scripts/test/simulate_compra.py --cantidad 10 --lotes 3
python scripts/test/simulate_compra.py --cantidad 10 --lotes 3 --lotes-pct 50,30,20
python scripts/test/simulate_compra.py --cantidad 5 --lotes 5 --flush
```

## Verificación

```sql
SELECT id, table_name, op, status, created_at
FROM sync_outbox
ORDER BY id DESC
LIMIT 10;
```

En el hub: ingest en tablas `store_*` y deltas en inventario agregado (según procesadores activos).
