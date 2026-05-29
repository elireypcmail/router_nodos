#!/usr/bin/env bash
# Desarrollo en macOS: MySQL (Docker), triggers/outbox, VPN opcional (wg0.conf), API en primer plano.
#
# Uso (desde cualquier ruta):
#   Multishop-nodo-API/scripts/mac/start-dev.sh
#   Multishop-nodo-API/scripts/mac/start-dev.sh --bundle-dir ~/Downloads/nodo-bundle
#
# Opciones:
#   --bundle-dir DIR   Copia .env y usa wg0.conf del bundle si existen
#   --no-wg            No intenta levantar WireGuard
#   --skip-triggers    No aplica outbox (triggers/funciones ms_json_*)
#   --skip-docker      Asume MySQL ya corriendo (usa MYSQL_* del .env)
#   --recreate-venv    Borra venv y lo recrea
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${NODO_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.mysql.yml"
MYSQL_CONTAINER="${MS_MYSQL_CONTAINER:-multishop-mysql-tienda}"
SQL_TRIGGERS="${NODO_DIR}/scripts/mysql_outbox_triggers.sql"
ENV_FILE="${NODO_DIR}/.env"
VENV_DIR="${NODO_DIR}/venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"

BUNDLE_DIR=""
NO_WG=0
SKIP_TRIGGERS=0
SKIP_DOCKER=0
RECREATE_VENV=0
WG_STARTED=0
WG_INTERFACE=""

log() { printf '\033[1;36m[multishop-mac]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[multishop-mac]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[multishop-mac]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --bundle-dir)
      BUNDLE_DIR="${2:-}"
      [[ -n "${BUNDLE_DIR}" ]] || die "Falta ruta tras --bundle-dir"
      shift 2
      ;;
    --no-wg) NO_WG=1; shift ;;
    --skip-triggers) SKIP_TRIGGERS=1; shift ;;
    --skip-docker) SKIP_DOCKER=1; shift ;;
    --recreate-venv) RECREATE_VENV=1; shift ;;
    *) die "Opción desconocida: $1 (usa --help)" ;;
  esac
done

cleanup() {
  local code=$?
  if [[ "${WG_STARTED}" -eq 1 && -n "${WG_INTERFACE}" ]]; then
    log "Bajando WireGuard (${WG_INTERFACE})..."
    sudo wg-quick down "${WG_INTERFACE}" 2>/dev/null || true
  fi
  exit "${code}"
}
trap cleanup EXIT INT TERM

load_env_var() {
  local key="$1"
  local line val
  [[ -f "${ENV_FILE}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ "${line}" =~ ^[[:space:]]*$ ]] && continue
    [[ "${line}" =~ ^${key}= ]] || continue
    val="${line#*=}"
    val="${val#\"}"; val="${val%\"}"
    val="${val#\'}"; val="${val%\'}"
    printf '%s' "${val}"
    return 0
  done < "${ENV_FILE}"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Falta '$1' en PATH. $2"
}

find_python3() {
  local candidates=()
  if [[ -n "${PYTHON:-}" ]]; then candidates+=("${PYTHON}"); fi
  candidates+=(python3.13 python3.12 python3.11 python3)
  local c
  for c in "${candidates[@]}"; do
    if command -v "${c}" >/dev/null 2>&1; then
      printf '%s' "$(command -v "${c}")"
      return 0
    fi
  done
  return 1
}

ensure_python() {
  local py
  if ! py="$(find_python3)"; then
    die "No se encontró Python 3.11+. Instala con: brew install python@3.12"
  fi
  local ver
  ver="$("${py}" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  log "Python: ${py} (${ver})"
  if ! "${py}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    warn "Se recomienda Python 3.11+ (tienes ${ver})"
  fi
  printf '%s' "${py}"
}

ensure_venv() {
  local py="$1"
  if [[ "${RECREATE_VENV}" -eq 1 && -d "${VENV_DIR}" ]]; then
    log "Recreando venv..."
    rm -rf "${VENV_DIR}"
  fi
  if [[ ! -d "${VENV_DIR}" ]]; then
    log "Creando venv en ${VENV_DIR}..."
    "${py}" -m venv "${VENV_DIR}"
  fi
  log "Instalando dependencias (pip)..."
  "${PIP_BIN}" install -q --upgrade pip
  "${PIP_BIN}" install -q -r "${NODO_DIR}/requirements.txt"
}

apply_bundle() {
  [[ -n "${BUNDLE_DIR}" ]] || return 0
  [[ -d "${BUNDLE_DIR}" ]] || die "No existe --bundle-dir: ${BUNDLE_DIR}"
  if [[ -f "${BUNDLE_DIR}/.env" ]]; then
    cp "${BUNDLE_DIR}/.env" "${ENV_FILE}"
    log "Copiado .env desde bundle"
  fi
}

find_wg0_conf() {
  local paths=()
  [[ -n "${BUNDLE_DIR}" ]] && paths+=("${BUNDLE_DIR}/wg0.conf" "${BUNDLE_DIR}/vpn/wg0.conf")
  paths+=(
    "${NODO_DIR}/wg0.conf"
    "${NODO_DIR}/vpn/wg0.conf"
    "${REPO_ROOT}/nodo/wg0.conf"
  )
  local p
  for p in "${paths[@]}"; do
    if [[ -f "${p}" ]]; then
      printf '%s' "${p}"
      return 0
    fi
  done
  return 1
}

wireguard_interface_name() {
  local conf="$1"
  local name
  name="$(grep -E '^[[:space:]]*\[Interface\]' -A20 "${conf}" | grep -E '^[[:space:]]*Name[[:space:]]*=' | head -1 | sed -E 's/^[[:space:]]*Name[[:space:]]*=[[:space:]]*//; s/[[:space:]]+$//' || true)"
  if [[ -n "${name}" ]]; then
    printf '%s' "${name}"
  else
    printf 'wg0'
  fi
}

ensure_wireguard() {
  [[ "${NO_WG}" -eq 1 ]] && return 0
  local conf
  if ! conf="$(find_wg0_conf)"; then
    warn "Sin wg0.conf (buscado en nodo, vpn/ y bundle). API por red normal."
    return 0
  fi
  if ! command -v wg >/dev/null 2>&1 || ! command -v wg-quick >/dev/null 2>&1; then
    warn "WireGuard CLI no instalado. Instala: brew install wireguard-tools"
    warn "O importa ${conf} en la app WireGuard (Mac App Store)."
    return 0
  fi

  WG_INTERFACE="$(wireguard_interface_name "${conf}")"
  if sudo wg show "${WG_INTERFACE}" >/dev/null 2>&1; then
    log "WireGuard ya activo: ${WG_INTERFACE}"
    return 0
  fi

  local dest_dir
  if [[ "$(uname -m)" == "arm64" ]] && [[ -d "/opt/homebrew/etc/wireguard" ]]; then
    dest_dir="/opt/homebrew/etc/wireguard"
  elif [[ -d "/usr/local/etc/wireguard" ]]; then
    dest_dir="/usr/local/etc/wireguard"
  else
    dest_dir="/tmp/multishop-wireguard"
    mkdir -p "${dest_dir}"
  fi

  local dest="${dest_dir}/${WG_INTERFACE}.conf"
  log "WireGuard: ${conf} → ${dest}"
  sudo mkdir -p "${dest_dir}"
  sudo cp "${conf}" "${dest}"
  sudo chmod 600 "${dest}"

  sudo wg-quick down "${WG_INTERFACE}" 2>/dev/null || true
  if sudo wg-quick up "${WG_INTERFACE}"; then
    WG_STARTED=1
    log "VPN activa (${WG_INTERFACE}). Ping hub: ping -c1 10.66.0.1"
  else
    warn "No se pudo levantar wg-quick. Prueba la app WireGuard con el mismo .conf."
  fi
}

docker_mysql_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${MYSQL_CONTAINER}"
}

wait_mysql() {
  local user="${MYSQL_USER:-multishop}"
  local pass="${MYSQL_PASSWORD:-multishop}"
  local tries=0
  log "Esperando MySQL en ${MYSQL_CONTAINER}..."
  while [[ "${tries}" -lt 60 ]]; do
    if docker exec "${MYSQL_CONTAINER}" mysqladmin ping -h127.0.0.1 -u"${user}" -p"${pass}" --silent 2>/dev/null; then
      log "MySQL listo."
      return 0
    fi
    tries=$((tries + 1))
    sleep 2
  done
  die "MySQL no respondió a tiempo. Revisa: docker logs ${MYSQL_CONTAINER}"
}

ensure_docker_mysql() {
  [[ "${SKIP_DOCKER}" -eq 1 ]] && return 0
  require_cmd docker "Instala Docker Desktop para Mac."
  if ! docker info >/dev/null 2>&1; then
    die "Docker no está corriendo. Abre Docker Desktop."
  fi
  [[ -f "${COMPOSE_FILE}" ]] || die "No existe ${COMPOSE_FILE}"

  if docker_mysql_running; then
    log "Contenedor ${MYSQL_CONTAINER} ya en ejecución."
  else
    log "Levantando MySQL: docker compose -f ${COMPOSE_FILE} up -d"
    docker compose -f "${COMPOSE_FILE}" up -d
  fi
  wait_mysql
}

export_mysql_env_for_scripts() {
  export MS_MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
  export MS_MYSQL_PORT="${MYSQL_PORT:-3306}"
  export MS_MYSQL_USER="${MYSQL_USER}"
  export MS_MYSQL_PASSWORD="${MYSQL_PASSWORD}"
  export MS_MYSQL_DATABASE="${MYSQL_DATABASE}"
}

wait_mysql_app() {
  export_mysql_env_for_scripts
  export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
  export MYSQL_PORT="${MYSQL_PORT:-3306}"
  export MYSQL_USER="${MYSQL_USER}"
  export MYSQL_PASSWORD="${MYSQL_PASSWORD}"
  export MYSQL_DATABASE="${MYSQL_DATABASE}"
  log "Comprobando MySQL desde el host (${MYSQL_HOST}:${MYSQL_PORT}, usuario ${MYSQL_USER})..."
  if ! "${PYTHON_BIN}" "${NODO_DIR}/scripts/mysql_wait_ready.py"; then
    die "MySQL no acepta conexiones desde la API. Revisa: docker logs ${MYSQL_CONTAINER}"
  fi
}

ensure_triggers() {
  [[ "${SKIP_TRIGGERS}" -eq 1 ]] && return 0
  [[ -f "${SQL_TRIGGERS}" ]] || die "No existe ${SQL_TRIGGERS}"

  log "Outbox: desinstalar triggers Multishop y reinstalar desde cero..."
  export_mysql_env_for_scripts
  export MS_SQL_FILE="${SQL_TRIGGERS}"
  unset MS_OUTBOX_SKIP_PREFLIGHT

  if ! "${PYTHON_BIN}" "${NODO_DIR}/scripts/apply_mysql_outbox_triggers.py"; then
    die "Falló apply_mysql_outbox_triggers.py"
  fi
}

read_mysql_from_env() {
  MYSQL_HOST="$(load_env_var MYSQL_HOST)"
  MYSQL_PORT="$(load_env_var MYSQL_PORT)"
  MYSQL_USER="$(load_env_var MYSQL_USER)"
  MYSQL_PASSWORD="$(load_env_var MYSQL_PASSWORD)"
  MYSQL_DATABASE="$(load_env_var MYSQL_DATABASE)"
  MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
  MYSQL_PORT="${MYSQL_PORT:-3306}"
}

# --- main ---
log "Nodo: ${NODO_DIR}"
log "Repo: ${REPO_ROOT}"

apply_bundle

[[ -f "${ENV_FILE}" ]] || die "Crea ${ENV_FILE} (copia .env.example o bundle provisioning)."

read_mysql_from_env
if [[ -z "${MYSQL_USER}" || -z "${MYSQL_PASSWORD}" || -z "${MYSQL_DATABASE}" ]]; then
  die "MYSQL_USER, MYSQL_PASSWORD y MYSQL_DATABASE son obligatorios en .env"
fi

py="$(ensure_python)"
ensure_venv "${py}"

ensure_docker_mysql
ensure_triggers
# Misma ruta que la API (host → 127.0.0.1:3306); tras triggers MySQL puede tardar un poco.
wait_mysql_app
ensure_wireguard

cd "${NODO_DIR}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
# Reload opcional (puede provocar bucles si watchfiles ve cambios en venv/cache).
# Tras cambiar rutas Python: reinicia start-dev.sh o export NODO_DEV_RELOAD=true
export NODO_DEV_RELOAD="${NODO_DEV_RELOAD:-false}"

log "Variables: MYSQL_HOST=${MYSQL_HOST} MYSQL_DATABASE=${MYSQL_DATABASE}"
log "Hub: HUB_BASE_URL=$(load_env_var HUB_BASE_URL) HUB_PUSH_ENABLED=$(load_env_var HUB_PUSH_ENABLED) HUEY_ENABLED=$(load_env_var HUEY_ENABLED)"

HUEY_PID=""
cleanup_dev() {
  if [[ -n "${HUEY_PID}" ]]; then
    kill "${HUEY_PID}" 2>/dev/null || true
  fi
}
trap cleanup_dev EXIT INT TERM

if [[ "$(load_env_var HUEY_ENABLED)" == "true" ]]; then
  log "Iniciando Huey consumer en background..."
  "${PYTHON_BIN}" -m huey.bin.huey_consumer huey_tasks.huey &
  HUEY_PID=$!
fi

log "Iniciando API (Ctrl+C para salir). Logs abajo."
echo "────────────────────────────────────────────────────────"

"${PYTHON_BIN}" main.py
