#!/bin/sh
# Materializa /app/.env desde variables de entorno (env_file de compose + overrides).
# La API (config.py) y scripts de test leen siempre Multishop-nodo-API/.env en /app.
set -eu

DOTENV_PATH="${NODO_DOTENV_PATH:-/app/.env}"
SOURCE_FILE="${NODO_ENV_SOURCE:-}"

if [ -n "${SOURCE_FILE}" ] && [ -f "${SOURCE_FILE}" ]; then
  cp "${SOURCE_FILE}" "${DOTENV_PATH}"
  echo "[nodo-api] .env desde ${SOURCE_FILE} → ${DOTENV_PATH}"
  exit 0
fi

if [ -f "${DOTENV_PATH}" ] && [ "${NODO_REFRESH_DOTENV:-false}" != "true" ]; then
  echo "[nodo-api] Usando ${DOTENV_PATH} existente (NODO_REFRESH_DOTENV=true para regenerar)"
  exit 0
fi

# Mismo orden / claves que el bundle de provisioning (hub).
keys="
NODO_ID
NODO_NOMBRE
NODO_ROLE
NODO_API_TOKEN
NODO_HOST
NODO_PORT
NODO_ALLOW_INSECURE
HUB_BASE_URL
HUB_API_KEY
HUB_PUSH_ENABLED
SYNC_WORKER_ENABLED
SYNC_DB_PATH
MYSQL_HOST
MYSQL_PORT
MYSQL_USER
MYSQL_PASSWORD
MYSQL_DATABASE
HUEY_ENABLED
HUEY_DB_PATH
"

tmp="${DOTENV_PATH}.tmp.$$"
: > "${tmp}"
written=0

for key in ${keys}; do
  eval "val=\${${key}-}"
  if [ -n "${val}" ]; then
    printf '%s=%s\n' "${key}" "${val}" >> "${tmp}"
    written=$((written + 1))
  fi
done

if [ "${written}" -eq 0 ]; then
  echo "[nodo-api] ERROR: no hay variables para escribir ${DOTENV_PATH}. ¿env_file en compose?" >&2
  exit 1
fi

if [ -z "${NODO_API_TOKEN:-}" ] || [ "${NODO_API_TOKEN}" = "dev-token-change-me" ]; then
  echo "[nodo-api] ERROR: NODO_API_TOKEN vacío o placeholder. Copia envs/tienda-N.env tras provisioning." >&2
  exit 1
fi

mv "${tmp}" "${DOTENV_PATH}"
chmod 600 "${DOTENV_PATH}" 2>/dev/null || true
token_tail=$(printf '%s' "${NODO_API_TOKEN}" | tail -c 9)
echo "[nodo-api] Escrito ${DOTENV_PATH} (${written} variables, NODO_API_TOKEN=…${token_tail})"
