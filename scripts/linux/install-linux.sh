#!/usr/bin/env bash
# Instala/configura nodo en Linux (WireGuard + API Python)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
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
HUEY_ENABLED=""
HUB_PUSH_ENABLED=""
ROUTER_EVENTS_URL=""

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
      HUEY_ENABLED) HUEY_ENABLED="${v}" ;;
      HUB_PUSH_ENABLED) HUB_PUSH_ENABLED="${v}" ;;
      ROUTER_EVENTS_URL) ROUTER_EVENTS_URL="${v}" ;;
    esac
  done < "${NODO_DIR}/.env"
fi

HUEY_ENABLED="${HUEY_ENABLED:-}"
HUB_PUSH_ENABLED="${HUB_PUSH_ENABLED:-}"
ROUTER_EVENTS_URL="${ROUTER_EVENTS_URL:-}"

needs_outbox_triggers() {
  [[ "${HUEY_ENABLED}" == "true" ]] && return 0
  [[ "${HUB_PUSH_ENABLED}" == "true" ]] && return 0
  [[ -n "${ROUTER_EVENTS_URL// }" ]] && return 0
  return 1
}

outbox_sql_file() {
  local mov="${NODO_DIR}/scripts/mysql_outbox_triggers_movimientos.sql"
  if [[ -f "${mov}" ]]; then
    printf '%s' "${mov}"
    return 0
  fi
  printf '%s' "${NODO_DIR}/scripts/mysql_outbox_triggers.sql"
}

if [[ -z "${MYSQL_PORT}" ]]; then
  MYSQL_PORT="3306"
fi

python3 -m venv "${NODO_DIR}/venv"
"${NODO_DIR}/venv/bin/pip" install -q -r "${NODO_DIR}/requirements.txt"

apply_outbox_triggers() {
  if [[ -z "${MYSQL_HOST}" || -z "${MYSQL_USER}" || -z "${MYSQL_PASSWORD}" || -z "${MYSQL_DATABASE}" ]]; then
    echo "Aviso: MYSQL_* incompleto en .env. Omitiendo outbox (triggers)." >&2
    return 0
  fi
  export MS_MYSQL_HOST="${MYSQL_HOST}"
  export MS_MYSQL_PORT="${MYSQL_PORT}"
  export MS_MYSQL_USER="${MYSQL_USER}"
  export MS_MYSQL_PASSWORD="${MYSQL_PASSWORD}"
  export MS_MYSQL_DATABASE="${MYSQL_DATABASE}"
  export MS_SQL_FILE="$(outbox_sql_file)"
  unset MS_OUTBOX_SKIP_PREFLIGHT
  echo "Outbox: desinstalar triggers Multishop y reinstalar (apply_mysql_outbox_triggers.py)..."
  "${NODO_DIR}/venv/bin/python" "${NODO_DIR}/scripts/apply_mysql_outbox_triggers.py"
}

if needs_outbox_triggers; then
  apply_outbox_triggers || echo "Aviso: no se pudo aplicar outbox. Revise MySQL y permisos TRIGGER." >&2
else
  echo "Outbox/triggers omitidos (HUEY_ENABLED, ROUTER_EVENTS_URL y HUB_PUSH_ENABLED no activan outbox)."
fi

echo "Nodo Linux listo. Arranque API: ${NODO_DIR}/venv/bin/python ${NODO_DIR}/main.py"
echo ""
if [[ "${HUEY_ENABLED}" == "true" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    echo "Registrando Huey consumer (systemd)..."
    bash "${NODO_DIR}/scripts/linux/install-huey-systemd.sh"
  else
    echo "Huey (HUEY_ENABLED=true): arranque manual en otra terminal:"
    echo "  ${NODO_DIR}/scripts/start-huey-consumer.sh"
  fi
else
  echo "Huey desactivado (HUEY_ENABLED no es true en .env)."
fi
