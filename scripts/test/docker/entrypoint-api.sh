#!/bin/sh
set -eu

cd /app

# 1) .env en la raíz de la API (config.py, scripts/test, workers)
/app/scripts/test/docker/write-app-dotenv.sh

echo "[nodo-api] Esperando MySQL (${MYSQL_HOST:-?}:${MYSQL_PORT:-3306})..."
python scripts/mysql_wait_ready.py

/app/scripts/test/docker/wait-erp-schema.sh

if [ "${NODO_APPLY_OUTBOX_TRIGGERS:-true}" = "true" ]; then
  echo "[nodo-api] Aplicando triggers outbox (mysql_outbox_triggers.sql)..."
  export MS_MYSQL_HOST="${MYSQL_HOST}"
  export MS_MYSQL_PORT="${MYSQL_PORT:-3306}"
  export MS_MYSQL_USER="${MYSQL_USER}"
  export MS_MYSQL_PASSWORD="${MYSQL_PASSWORD}"
  export MS_MYSQL_DATABASE="${MYSQL_DATABASE}"
  export MS_SQL_FILE="/app/scripts/mysql_outbox_triggers.sql"
  python scripts/apply_mysql_outbox_triggers.py || {
    echo "[nodo-api] Aviso: no se pudieron aplicar triggers (¿BD vacía o sin tablas ERP?)." >&2
  }
fi

huey_enabled=""
if [ -f /app/.env ]; then
  huey_enabled="$(grep -E '^HUEY_ENABLED=' /app/.env | head -n1 | cut -d= -f2- | tr -d '\r' || true)"
fi
if [ "${huey_enabled}" = "true" ]; then
  echo "[nodo-api] Iniciando Huey consumer (outbox + sync jobs)..."
  python -m huey.bin.huey_consumer huey_tasks.huey >>/app/data/huey-consumer.log 2>&1 &
fi

echo "[nodo-api] Iniciando API (${NODO_HOST:-0.0.0.0}:${NODO_PORT:-8443}, NODO_ID=${NODO_ID:-?})..."
exec python main.py
