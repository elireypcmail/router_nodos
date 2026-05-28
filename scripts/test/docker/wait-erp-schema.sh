#!/bin/sh
# Falla con mensaje claro si falta esquema ERP (sinv).
set -eu

DB="${MYSQL_DATABASE:-mi_base_historica}"
HOST="${MYSQL_HOST:-127.0.0.1}"
PORT="${MYSQL_PORT:-3306}"
USER="${MYSQL_USER:-multishop}"
PASS="${MYSQL_PASSWORD:-multishop}"

exists=$(mysql -h"${HOST}" -P"${PORT}" -u"${USER}" -p"${PASS}" -N -e \
  "SELECT COUNT(*) FROM information_schema.tables
   WHERE table_schema='${DB}' AND table_name='sinv'" 2>/dev/null || echo 0)

if [ "${exists}" = "1" ]; then
  echo "[nodo-api] Esquema ERP: tabla sinv presente en ${DB}."
  exit 0
fi

echo "[nodo-api] ERROR: en ${DB} no existe la tabla sinv (MySQL vacío)." >&2
echo "[nodo-api] Importa backup_seguro.sql.gz en las 3 tiendas:" >&2
echo "  cd Multishop-nodo-API && ./scripts/test/docker/import-backup-to-tiendas.sh" >&2
echo "[nodo-api] (o deja backup_seguro.sql.gz en la raíz del repo y: down -v && up -d)" >&2
exit 1
