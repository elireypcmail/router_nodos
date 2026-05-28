#!/bin/bash
# Primer arranque del volumen: importa backup_seguro.sql.gz desde /host-repo (raíz nodo-servidor).
set -e

DB="${MYSQL_DATABASE:-mi_base_historica}"
ROOT_PW="${MYSQL_ROOT_PASSWORD:-root}"
GZ="/host-repo/backup_seguro.sql.gz"
ENC="/host-repo/backup_seguro.sql.gz.enc"

import_stream() {
  if [ -f "${GZ}" ]; then
    echo "[mysql-init] Importando ${GZ} en ${DB}..."
    zcat "${GZ}"
    return 0
  fi
  if [ -f "${ENC}" ] && [ -n "${BACKUP_DECRYPT_PASS:-}" ]; then
    echo "[mysql-init] Descifrando e importando ${ENC} en ${DB}..."
    openssl enc -d -aes-256-cbc -pbkdf2 -in "${ENC}" \
      -pass "pass:${BACKUP_DECRYPT_PASS}" | gzip -dc
    return 0
  fi
  return 1
}

if import_stream | mysql -uroot -p"${ROOT_PW}" "${DB}"; then
  echo "[mysql-init] Backup listo en ${DB}."
else
  echo "[mysql-init] Aviso: sin backup en /host-repo (backup_seguro.sql.gz o .enc + BACKUP_DECRYPT_PASS)."
  echo "[mysql-init] Tras levantar el stack: ./scripts/test/docker/import-backup-to-tiendas.sh"
fi
