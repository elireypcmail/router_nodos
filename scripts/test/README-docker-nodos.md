# Nodos de prueba en Docker (3 tiendas)

Stack para levantar **tres tiendas** independientes: cada una con **MySQL 5.6** propio y la **API FastAPI** del nodo, conectadas a la red del hub dev (`multishop_hub_dev`).

Cada tienda carga el mismo **`backup_seguro.sql.gz`** (catálogo ERP completo en `mi_base_historica`).

## Requisitos

1. Hub dev en marcha (red `multishop_hub_dev`):

   ```bash
   cd <repo-root>
   docker compose -f docker-compose.dev.yml up -d
   ```

2. Backup en la **raíz del repo** `nodo-servidor/`:

   - `backup_seguro.sql.gz` (recomendado), o
   - `backup_seguro.sql.gz.enc` + contraseña al importar.

   Descifrar una vez (si solo tienes `.enc`):

   ```bash
   cd <repo-root>
   openssl enc -d -aes-256-cbc -pbkdf2 -in backup_seguro.sql.gz.enc \
     -pass pass:TU_CLAVE | gunzip > backup_seguro.sql.gz
   ```

3. `envs/tienda-N.env` con `NODO_ID` / `NODO_API_TOKEN` tras provisioning en hub-ui.

## Levantar

```bash
cd Multishop-nodo-API
docker compose -f scripts/test/docker-compose.nodos.yml up -d --build
```

## Cargar backup en las 3 MySQL

**Volúmenes ya existentes** (lo habitual tras un `up` previo):

```bash
cd Multishop-nodo-API
chmod +x scripts/test/docker/import-backup-to-tiendas.sh

# Si solo tienes .enc:
# export BACKUP_DECRYPT_PASS='tu-clave'

./scripts/test/docker/import-backup-to-tiendas.sh
docker compose -f scripts/test/docker-compose.nodos.yml restart \
  nodo-tienda-1 nodo-tienda-2 nodo-tienda-3
```

El script hace `DROP DATABASE` + import en cada `multishop-mysql-tienda-N` (tarda varios minutos por tienda).

**MySQL nuevos** (`down -v` y `up` de nuevo): si existe `backup_seguro.sql.gz` en la raíz del repo, el init lo importa solo al crear el volumen. Con `.enc`, define `BACKUP_DECRYPT_PASS` al hacer `up`:

```bash
cd Multishop-nodo-API
BACKUP_DECRYPT_PASS='tu-clave' \
  docker compose -f scripts/test/docker-compose.nodos.yml up -d
```

## Provisioning en hub-ui (modo **Internet**)

| Tienda | **publicApiHost** | **apiPort** |
|--------|-------------------|-------------|
| 1 | `nodo-tienda-1` | `8443` |
| 2 | `nodo-tienda-2` | `8443` |
| 3 | `nodo-tienda-3` | `8443` |

## Acceso desde el Mac

| Tienda | API | MySQL |
|--------|-----|-------|
| 1 | http://127.0.0.1:18443 | 127.0.0.1:13306 |
| 2 | http://127.0.0.1:18444 | 127.0.0.1:13307 |
| 3 | http://127.0.0.1:18445 | 127.0.0.1:13308 |

Simulaciones (misma BD que el contenedor):

```bash
export MYSQL_HOST=127.0.0.1 MYSQL_PORT=13306
export MYSQL_USER=multishop MYSQL_PASSWORD=multishop MYSQL_DATABASE=mi_base_historica
python scripts/test/simulate_compra.py --precio 1000 --cantidad 10 --flush
```

## Escenario costos (3 tiendas)

Mismo catálogo en las tres; ajusta `sinv.costo` / `costopro` por tienda en SQL para probar advertencias de costo en el hub.

## «Token inválido»

Revisa `envs/tienda-N.env` y que el compose **no** sobrescriba `NODO_API_TOKEN`. Logs: `Escrito /app/.env` en el contenedor API.

## Parar y limpiar

```bash
docker compose -f scripts/test/docker-compose.nodos.yml down
docker compose -f scripts/test/docker-compose.nodos.yml down -v   # borra datos MySQL
```
