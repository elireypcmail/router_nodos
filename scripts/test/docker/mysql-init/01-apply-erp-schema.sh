#!/bin/bash
# Solo en primer arranque del volumen MySQL (docker-entrypoint-initdb.d).
set -e
DB="${MYSQL_DATABASE:-mi_base_historica}"
ROOT_PW="${MYSQL_ROOT_PASSWORD:-root}"

apply() {
  echo "[mysql-init] Aplicando $(basename "$1")..."
  mysql -uroot -p"${ROOT_PW}" "${DB}" <"$1"
}

for f in /erp-schema/resumen/*.sql; do
  [ -f "$f" ] || continue
  apply "$f"
done

apply /erp-schema/docker/erp-schema-transaccional.sql
echo "[mysql-init] Esquema ERP base listo en ${DB}."
