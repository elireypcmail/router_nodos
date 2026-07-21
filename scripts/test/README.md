# Simulaciones transaccionales (MySQL → outbox → hub)

## Tres nodos en Docker

Para levantar **3 tiendas** con `backup_seguro.sql.gz` en cada MySQL: [README-docker-nodos.md](./README-docker-nodos.md).

Scripts que insertan en las tablas del ERP local para disparar los triggers de `sync_outbox_router` y el flujo hacia el router.

**Importante:** los triggers de outbox **no** actualizan `sinv`. Por defecto `simulate_compra.py` también hace `UPDATE sinv` de **existencia** y **costo/costopro** (CPP con `--precio`, misma lógica que el hub). Sin eso, el hub puede recibir el evento por `--flush`, pero **Sync existencia** en el portal lee `sinv` en la tienda y verá stock/costos viejos. Usa `--no-update-sinv` solo si quieres probar únicamente el outbox.

**Fechas (alineado con `./test` del monorepo padre):**

| Destino | Origen |
|---------|--------|
| `scom.fecha` | `--fecha` / columna CSV (fecha comercial) |
| `scst.fecha` / `fconfirma` / `hconfirma` | instante de ejecución (timezone tienda) |
| `kardex.fecha` + hora en `kobs` / `kardex.hora` | mismo instante de ejecución |
| `diariovi.fecha` | mismo instante de ejecución |

`NODO_STORE_TZ` (default `America/Caracas`). Así `movementTimestamp` del webhook coincide con fecha+hora del kardex, no con una fecha histórica del CSV mezclada con la hora actual.

`simulate_compra.py` además hace UPSERT en `detalle` (lote default, cubica `01`) para encolar `inventory_lot` y poblar lotes unificados en el hub. Requiere triggers `trg_detalle_*` en MySQL.

Con `--lotes N` crea **N** filas en `detalle` y reparte la cantidad de la compra entre ellas (`N` no puede ser mayor que `--cantidad`). Sin `--lotes-pct` reparte en partes iguales; con `--lotes-pct 50,30,20` usa esos porcentajes (deben coincidir con `N`).

## Requisitos

1. `.env` en `Multishop-nodo-API/` con `MYSQL_*` apuntando a la base de la tienda.
2. Tabla `sync_outbox_router` y triggers `trg_router_kardex_*` (MySQL **5.6**; el instalador reinstala solo objetos router):

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
4. Para enviar al router sin Huey: `ROUTER_EVENTS_URL` y `NODO_API_TOKEN` en `.env` y flag `--flush`.

Con la API en marcha y `HUEY_ENABLED=true` (default del provisioning), el **consumer Huey** envía los `pending` del outbox y ejecuta jobs de sync catálogo. En dev Mac: `scripts/mac/start-dev.sh` arranca Huey en background. No hace falta `--flush` salvo pruebas aisladas.

## Scripts (flujo ERP real)

Compras reales del ERP: línea en **`scom`** (`numero`, `subtotal2`, `costo`, `cantidad`) y luego movimiento en **`kardex`** + **`kardexd`**. El ERP **no** escribe `comprasdbf`. Ventas: **`kardex`** / **`kardexd`** (no `ventasi` como fuente principal).

Los triggers transaccionales encolan **`kardex`** solo desde la cabecera **`kardex`**. No hay triggers en **`kardexd`**, **`comprasdbf`** ni **`ventasi`**.

| Script | Tablas ERP | Outbox → hub |
|--------|------------|--------------|
| `simulate_compra.py` | **`scom`** + `kardex` + `kardexd` + `sinv` + `detalle` + `detallepr` + `historialc` + `historialp` | `kardex` → `purchase`; `historialp` → `price_change` (si trigger activo) |
| `simulate_venta.py` | `kardex` + `kardexd` + `detalle` | `kardex` → `sale`; `detalle` → `inventory_lot` |
| `simulate_kardex_ajuste.py` | `kardex` (cabecera) | `kardex` → ajuste |
| `simulate_kardex_devolucion.py` | `kardex` (cabecera) | `kardex` → devolución |

`generate_movimientos_csv.py` — genera `movimientos.csv` en la raíz del repo con movimientos aleatorios multi-nodo (fechas únicas, orden cronológico) para planificar pruebas CPP/portal:

```bash
python scripts/test/generate_movimientos_csv.py --codigo FF10000022 --nodos 4 --movimientos 30
python scripts/test/generate_movimientos_csv.py -m 40 --semilla 1
python scripts/test/generate_movimientos_csv.py --movimientos 40 --semilla 1 --output ../../movimientos.csv
```

Columnas: `fecha`, `nodo`, `codigo`, `tipo_movimiento`, `cantidad`, `precio`, `factor_cambio` (compras/ventas, 400–667), `inventario_inicial`, `inventario_final`. El inventario es **por nodo/tienda** (producto nuevo con existencia 0 en cada tienda). Cada fila cumple `inventario_final = inventario_inicial ± cantidad` según entrada/salida; la primera fila de cada nodo parte de 0. Tipos: `compra`, `venta`, `ajuste_entrada`, `ajuste_salida`, `devolucion_proveedor`. Opcional: `--stock-inicial Q`.

`plan_cpp_from_csv.py` — desde `movimientos.csv` genera `movimientos-cpp-plan.txt` y `movimientos-cpp-plan.csv` con orden ejecución, replay CPP hub (Exist.ant / Total uds agregado) y número scom probable (`DDMMYYYY` + `HHMMSS` al ejecutar):

```bash
python scripts/test/plan_cpp_from_csv.py
python scripts/test/plan_cpp_from_csv.py --match 10082025
```

`run_movimientos_csv.py` — ejecuta el CSV con los simuladores **en el orden de filas del archivo** (no reordena por fecha/nodo/tipo):

| Nodo CSV | Dónde corre |
|----------|-------------|
| 1, 2, 3 | Desde el **Mac**: `docker exec multishop-router-nodo-tienda-N python scripts/test/simulate_*.py` |
| 4 (default) | Mac en `Multishop-nodo-API/` con `.env` local (`--local-nodo` para otro número) |

**Orquestar todas las tiendas** (Mac, con Docker en PATH):

```bash
python scripts/test/run_movimientos_csv.py --dry-run
python scripts/test/run_movimientos_csv.py --flush
python scripts/test/run_movimientos_csv.py --flush --limit 5 --no-recalc-precios
```

**Solo una tienda Docker** (dentro del contenedor; no hay `docker` dentro):

```bash
docker exec multishop-router-nodo-tienda-3 python scripts/test/run_movimientos_csv.py --flush
# o explícito:
docker exec multishop-router-nodo-tienda-3 python scripts/test/run_movimientos_csv.py --runner in-container --container-nodo 3 --flush
```

En modo contenedor se omiten filas de otros nodos del CSV. Para el flujo completo multi-tienda, ejecuta desde el Mac.

Por defecto espera **5 s** entre simuladores (`--delay 5`; `--delay 0` sin pausa). Útil con `--flush` para separar `eventOccurredAt` en el hub.

Por defecto inserta una **compra bootstrap** (`--lotes`) antes de la primera venta/salida de cada tienda si el CSV empieza sin stock en MySQL. Desactivar: `--no-bootstrap-stock`.

Modo legacy (tablas antiguas del simulador): `--legacy-comprasdbf` / `--legacy-ventasi`.

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
- `--fecha YYYY-MM-DD` — fecha comercial en **`scom.fecha`** (default: hoy). **kardex / diariovi / kobs** usan la fecha y hora de ejecución (timezone tienda `NODO_STORE_TZ`, default America/Caracas). Así `movementTimestamp` del webhook coincide con el instante real del simulador, no con una fecha histórica del CSV mezclada con la hora actual.
- `--dry-run` — no inserta, solo imprime el plan
- `--flush` — envía batch `pending` a `POST /api/nodo/events/batch`
- `--no-update-sinv` — no toca `sinv.existencia` (solo movimiento + outbox)

Solo `simulate_compra.py`:

- `--num-compra` — número en kobs `Compra#:` (default: `DDMMYYYY` + sufijo hora, único por ejecución)
- `--cod-prv` — proveedor en kobs (default: `sinv.cod_prv` → `sprv`)
- `--factor` — tipo de cambio factura (`scom.factor`, `detallepr.cambiodc`); **USD = Bs / factor** (default **400**)
- `--operador` — usuario en historialc/historialp (default `SUPERVISOR`)
- `--no-recalc-precios` — no recalcula precios ni escribe historialc/historialp
- `--legacy-comprasdbf` — INSERT directo en `comprasdbf` (ya no genera outbox; solo prueba SQL legacy)
- `--lotes N` — N filas `kardexd` + `detalle` (requiere `N <= --cantidad`)
- `--lotes-pct P1,P2,...` — reparto por % (misma cantidad de valores que `--lotes`)

Solo `simulate_venta.py`:

- `--numero` — ticket/factura en kobs `Vta#:`
- `--caja` / `--cliente` — texto en kobs
- `--lote` — descontar solo de ese lote (default: FEFO por vencimiento)
- `--cubica` — filtrar detalle por cubica
- `--sin-lotes` — no usa `detalle`; solo descuenta `sinv.existencia`
- `--require-lotes` — exige filas en `detalle` (falla si no hay). **Por defecto**, si no hay lotes se descuenta solo `sinv`
- `--precio` — precio unitario Bs en diariovi (default: `sinv.precio1`)
- `--factor` — tipo de cambio del ticket (`diariovi.dolar`; default `detallepr.cambiodc` o 400)
- `--legacy-ventasi` — INSERT directo en `ventasi` (modo antiguo)

Con lotes: stock en `detalle` (p. ej. tras `simulate_compra.py --lotes`). Sin lotes: basta `sinv.existencia`. Con `--no-update-sinv` no toca `detalle` ni `sinv`. La línea **diariovi** (costo + subtotal2) es la que lleva precio al hub.

Ejemplos:

```bash
python scripts/test/simulate_compra.py --cantidad 10 --lotes 3
python scripts/test/simulate_compra.py --fecha 2026-06-01 --cantidad 5 --flush
python scripts/test/simulate_compra.py --cantidad 10 --precio 150 --factor 60
python scripts/test/simulate_compra.py --cantidad 10 --lotes 3 --lotes-pct 50,30,20
python scripts/test/simulate_compra.py --cantidad 5 --lotes 5 --flush
python scripts/test/simulate_venta.py --codigo FF10000021 --cantidad 3 --flush
python scripts/test/simulate_venta.py --codigo FF00592 --cantidad 3
python scripts/test/simulate_venta.py --codigo FF00592 --cantidad 3 --sin-lotes
python scripts/test/simulate_venta.py --fecha 2026-06-15 --codigo FF10000021 --cantidad 2
python scripts/test/simulate_kardex_ajuste.py --fecha 2026-05-20 --direccion salida
```

## Verificación

```sql
SELECT id, table_name, op, status, created_at
FROM sync_outbox_router
ORDER BY id DESC
LIMIT 10;
```

En el hub: ingest en tablas `store_*` y deltas en inventario agregado (según procesadores activos).
