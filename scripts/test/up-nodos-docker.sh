#!/usr/bin/env bash
# Levanta los 3 nodos de prueba (requiere red multishop_hub_dev del hub dev).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="${ROOT}/scripts/test/docker-compose.nodos.yml"
ENVS_DIR="${ROOT}/scripts/test/envs"

if ! docker network inspect multishop_hub_dev >/dev/null 2>&1; then
  echo "Red multishop_hub_dev no existe. Primero:" >&2
  echo "  cd <repo-root> && docker compose -f docker-compose.dev.yml up -d" >&2
  exit 1
fi

for n in 1 2 3; do
  f="${ENVS_DIR}/tienda-${n}.env"
  if [[ ! -f "${f}" ]]; then
    echo "Aviso: no existe ${f}; se usan valores por defecto del compose." >&2
    echo "  Tras provisioning: cp ${ENVS_DIR}/tienda-${n}.env.example ${f}" >&2
  fi
done

cd "${ROOT}"
exec docker compose -f "${COMPOSE_FILE}" up -d --build "$@"
