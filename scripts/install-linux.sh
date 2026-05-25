#!/usr/bin/env bash
# Instala/configura nodo en Linux (WireGuard + API Python)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODO_DIR="$(dirname "${SCRIPT_DIR}")"
BUNDLE_DIR="${1:-.}"

if [[ -f "${BUNDLE_DIR}/wg0.conf" ]]; then
  if command -v wg >/dev/null 2>&1; then
    sudo cp "${BUNDLE_DIR}/wg0.conf" /etc/wireguard/wg0.conf
    sudo chmod 600 /etc/wireguard/wg0.conf
    sudo wg-quick down wg0 2>/dev/null || true
    sudo wg-quick up wg0
  else
    echo "Aviso: se encontró wg0.conf pero wireguard (wg) no está instalado. Continuando sin VPN (red normal)." >&2
  fi
else
  echo "Aviso: no se encontró wg0.conf. Continuando sin VPN (red normal)." >&2
fi

if [[ -f "${BUNDLE_DIR}/.env" ]]; then
  cp "${BUNDLE_DIR}/.env" "${NODO_DIR}/.env"
fi

MYSQL_HOST=""
MYSQL_PORT=""
MYSQL_USER=""
MYSQL_PASSWORD=""
MYSQL_DATABASE=""

if [[ -f "${NODO_DIR}/.env" ]]; then
  while IFS='=' read -r k v; do
    [[ -z "${k}" ]] && continue
    [[ "${k}" =~ ^# ]] && continue
    v="${v%\r}"
    v="${v%\n}"
    v="${v%\"}"
    v="${v#\"}"
    v="${v%\'}"
    v="${v#\'}"
    case "${k}" in
      MYSQL_HOST) MYSQL_HOST="${v}" ;;
      MYSQL_PORT) MYSQL_PORT="${v}" ;;
      MYSQL_USER) MYSQL_USER="${v}" ;;
      MYSQL_PASSWORD) MYSQL_PASSWORD="${v}" ;;
      MYSQL_DATABASE) MYSQL_DATABASE="${v}" ;;
    esac
  done < "${NODO_DIR}/.env"
fi

if [[ -z "${MYSQL_PORT}" ]]; then
  MYSQL_PORT="3306"
fi

TRIGGERS_DONE=0

if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' | grep -q '^mysql56-app$'; then
    echo "Activando triggers/outbox en MySQL (Docker: mysql56-app, DB: mi_base_restaurada)..."
    echo "Tablas CDC: sinv, sprv, ventas/ventasd, factura/facturad, kardex/kardexd, comprasdbf, catego"
    docker exec -i mysql56-app mysql -u root -pmultishop -D mi_base_restaurada < "${NODO_DIR}/scripts/mysql_outbox_triggers.sql"
    TRIGGERS_DONE=1
  fi
fi

if [[ "${TRIGGERS_DONE}" -eq 0 ]]; then
  if [[ -n "${MYSQL_HOST}" && -n "${MYSQL_USER}" && -n "${MYSQL_PASSWORD}" && -n "${MYSQL_DATABASE}" ]]; then
    if command -v mysql >/dev/null 2>&1; then
      echo "Validando conectividad MySQL (${MYSQL_HOST}:${MYSQL_PORT} / ${MYSQL_DATABASE} / usuario ${MYSQL_USER}) ..."
      if ! MYSQL_PWD="${MYSQL_PASSWORD}" mysql -h "${MYSQL_HOST}" -P "${MYSQL_PORT}" -u "${MYSQL_USER}" "${MYSQL_DATABASE}" -e "SELECT 1" >/dev/null 2>&1; then
        echo "ERROR: No se pudo conectar a MySQL. Revise host/puerto/credenciales/db en .env" >&2
      else
        echo "Aplicando triggers/outbox en MySQL (local/remoto)..."
        MYSQL_PWD="${MYSQL_PASSWORD}" mysql -h "${MYSQL_HOST}" -P "${MYSQL_PORT}" -u "${MYSQL_USER}" "${MYSQL_DATABASE}" < "${NODO_DIR}/scripts/mysql_outbox_triggers.sql"
      fi
    else
      echo "Aviso: no hay cliente mysql instalado. Omitiendo activación de triggers/outbox fuera de Docker." >&2
      echo "Instale mysql-client o ejecute el SQL manualmente en su servidor MySQL." >&2
    fi
  else
    echo "Aviso: MYSQL_* incompleto en .env. Omitiendo activación de triggers/outbox fuera de Docker." >&2
  fi
fi

python3 -m venv "${NODO_DIR}/venv"
"${NODO_DIR}/venv/bin/pip" install -r "${NODO_DIR}/requirements.txt"

echo "Nodo Linux listo. Arranque API: ${NODO_DIR}/venv/bin/python ${NODO_DIR}/main.py"
echo ""
echo "Huey (opcional, recomendado para reintentos de outbox):"
echo "- En .env: HUEY_ENABLED=true (y configure HUB_* + MYSQL_*)"
echo "- Arranque Huey consumer: ${NODO_DIR}/venv/bin/python -m huey.bin.huey_consumer huey_tasks.huey"
