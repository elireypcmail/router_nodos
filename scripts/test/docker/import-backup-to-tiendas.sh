#!/usr/bin/env bash
# Carga backup_seguro.sql.gz en las 3 MySQL de prueba (mismo catálogo en cada tienda).
#
# Archivo (uno de):
#   <repo>/backup_seguro.sql.gz
#   <repo>/backup_seguro.sql.gz.enc  + variable BACKUP_DECRYPT_PASS
#
# Uso:
#   cd Multishop-nodo-API
#   ./scripts/test/docker/import-backup-to-tiendas.sh
#   BACKUP_DECRYPT_PASS='...' ./scripts/test/docker/import-backup-to-tiendas.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
BACKUP_GZ="${BACKUP_SQL_GZ:-${REPO_ROOT}/backup_seguro.sql.gz}"
BACKUP_ENC="${BACKUP_SQL_GZ_ENC:-${REPO_ROOT}/backup_seguro.sql.gz.enc}"
DB="${MYSQL_DATABASE:-mi_base_historica}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-root}"

CONTAINERS=(
  multishop-mysql-tienda-1
  multishop-mysql-tienda-2
  multishop-mysql-tienda-3
)

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Uso: $0 [contenedor_mysql ...]" >&2
  echo "  BACKUP_SQL_GZ          ruta al .sql.gz (default: repo/backup_seguro.sql.gz)" >&2
  echo "  BACKUP_DECRYPT_PASS    si solo existe .enc" >&2
  exit 0
fi

if [[ $# -gt 0 ]]; then
  CONTAINERS=("$@")
fi

open_backup_stream() {
  if [[ -f "${BACKUP_GZ}" ]]; then
    echo "[backup] Leyendo ${BACKUP_GZ}" >&2
    gzip -dc "${BACKUP_GZ}"
    return 0
  fi
  if [[ -f "${BACKUP_ENC}" && -n "${BACKUP_DECRYPT_PASS:-}" ]]; then
    echo "[backup] Descifrando ${BACKUP_ENC}" >&2
    openssl enc -d -aes-256-cbc -pbkdf2 -in "${BACKUP_ENC}" \
      -pass "pass:${BACKUP_DECRYPT_PASS}" | gzip -dc
    return 0
  fi
  echo "No se encontró backup listo para importar." >&2
  echo "  Esperado: ${BACKUP_GZ}" >&2
  echo "  O: ${BACKUP_ENC} con BACKUP_DECRYPT_PASS en el entorno." >&2
  echo "" >&2
  echo "Descifrar una vez en el repo:" >&2
  echo "  openssl enc -d -aes-256-cbc -pbkdf2 -in backup_seguro.sql.gz.enc \\" >&2
  echo "    -pass pass:TU_CLAVE | gunzip > backup_seguro.sql.gz" >&2
  return 1
}

import_container() {
  local c="$1"
  echo "=== ${c} ==="
  if ! docker ps --format '{{.Names}}' | grep -qx "${c}"; then
    echo "Contenedor no en ejecución: ${c}" >&2
    return 1
  fi
  echo "[${c}] Recreando ${DB}..."
  docker exec "${c}" mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -e \
    "DROP DATABASE IF EXISTS \`${DB}\`; CREATE DATABASE \`${DB}\` CHARACTER SET latin1 COLLATE latin1_swedish_ci;"
  echo "[${c}] Importando dump (varios minutos)..."
  open_backup_stream | docker exec -i "${c}" mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "${DB}"
  echo "[${c}] OK"
}

for c in "${CONTAINERS[@]}"; do
  import_container "${c}"
done

echo ""
echo "Reinicia las APIs y aplica triggers outbox:"
echo "  docker compose -f scripts/test/docker-compose.nodos.yml restart nodo-tienda-1 nodo-tienda-2 nodo-tienda-3"
