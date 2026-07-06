#!/usr/bin/env bash
# Instala/configura nodo en macOS: .env del bundle, venv, triggers outbox (movimientos), Huey opcional.
#
# Uso:
#   ./scripts/mac/install-mac.sh [BUNDLE_DIR]
#   ./scripts/mac/install-mac.sh ~/Downloads/mi-tienda-bundle
#
# Requiere Python 3.11+ y acceso MySQL según MYSQL_* del .env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUNDLE_DIR="${1:-.}"
VENV_DIR="${NODO_DIR}/venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"

MYSQL_HOST=""
MYSQL_PORT=""
MYSQL_USER=""
MYSQL_PASSWORD=""
MYSQL_DATABASE=""
HUEY_ENABLED=""
HUB_PUSH_ENABLED=""
ROUTER_EVENTS_URL=""

log() { printf '\033[1;36m[multishop-mac-install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[multishop-mac-install]\033[0m %s\n' "$*" >&2; }

find_python3() {
  local candidates=()
  if [[ -n "${PYTHON:-}" ]]; then candidates+=("${PYTHON}"); fi
  candidates+=(python3.13 python3.12 python3.11 python3)
  local c
  for c in "${candidates[@]}"; do
    if command -v "${c}" >/dev/null 2>&1; then
      command -v "${c}"
      return 0
    fi
  done
  return 1
}

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

read_env_file() {
  local env_file="${NODO_DIR}/.env"
  [[ -f "${env_file}" ]] || return 0
  while IFS='=' read -r k v; do
    [[ -z "${k}" ]] && continue
    [[ "${k}" =~ ^# ]] && continue
    v="${v%\r}"
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
  done < "${env_file}"
}

if [[ -f "${BUNDLE_DIR}/.env" ]]; then
  cp "${BUNDLE_DIR}/.env" "${NODO_DIR}/.env"
  log ".env copiado desde ${BUNDLE_DIR}"
elif [[ -f "${BUNDLE_DIR}/env.txt" ]]; then
  cp "${BUNDLE_DIR}/env.txt" "${NODO_DIR}/.env"
  log ".env copiado desde ${BUNDLE_DIR}/env.txt"
else
  warn "No se encontró .env en ${BUNDLE_DIR}; se usa el .env existente en ${NODO_DIR}"
fi

read_env_file
MYSQL_PORT="${MYSQL_PORT:-3306}"

py="$(find_python3)" || {
  echo "No se encontró Python 3.11+. Instala con: brew install python@3.12" >&2
  exit 1
}
log "Python: ${py}"

if [[ ! -d "${VENV_DIR}" ]]; then
  log "Creando venv en ${VENV_DIR} ..."
  "${py}" -m venv "${VENV_DIR}"
fi

log "Instalando dependencias (pip) ..."
"${PIP_BIN}" install -q -r "${NODO_DIR}/requirements.txt"

mkdir -p "${NODO_DIR}/data"

apply_outbox_triggers() {
  if [[ -z "${MYSQL_HOST}" || -z "${MYSQL_USER}" || -z "${MYSQL_PASSWORD}" || -z "${MYSQL_DATABASE}" ]]; then
    warn "MYSQL_* incompleto en .env. Omitiendo outbox (triggers)."
    return 0
  fi
  export MS_MYSQL_HOST="${MYSQL_HOST}"
  export MS_MYSQL_PORT="${MYSQL_PORT}"
  export MS_MYSQL_USER="${MYSQL_USER}"
  export MS_MYSQL_PASSWORD="${MYSQL_PASSWORD}"
  export MS_MYSQL_DATABASE="${MYSQL_DATABASE}"
  export MS_SQL_FILE="$(outbox_sql_file)"
  unset MS_OUTBOX_SKIP_PREFLIGHT
  log "Outbox movimientos: apply_mysql_outbox_triggers.py ..."
  "${PYTHON_BIN}" "${NODO_DIR}/scripts/apply_mysql_outbox_triggers.py"
}

if needs_outbox_triggers; then
  apply_outbox_triggers || warn "No se pudo aplicar outbox. Revise MySQL y permisos TRIGGER."
else
  log "Outbox/triggers omitidos (HUEY_ENABLED, ROUTER_EVENTS_URL y HUB_PUSH_ENABLED no activan outbox)."
fi

log "Nodo macOS listo. Arranque API: ${PYTHON_BIN} ${NODO_DIR}/main.py"
echo ""

if [[ "${HUEY_ENABLED}" == "true" ]]; then
  if command -v launchctl >/dev/null 2>&1; then
    log "Registrando Huey consumer (LaunchAgent) ..."
    bash "${SCRIPT_DIR}/install-huey-launchd.sh"
  else
    echo "Huey (HUEY_ENABLED=true): arranque manual en otra terminal:"
    echo "  ${NODO_DIR}/scripts/start-huey-consumer.sh"
  fi
else
  echo "Huey desactivado (HUEY_ENABLED no es true en .env)."
  echo "Para webhooks de movimientos: HUEY_ENABLED=true y ROUTER_EVENTS_URL en .env."
fi

echo ""
echo "Desarrollo interactivo (API + Huey en la misma sesión):"
echo "  cd ${NODO_DIR} && ./start-dev.sh"
