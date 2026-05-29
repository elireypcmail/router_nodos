#!/usr/bin/env bash
# Arranca el consumer Huey (outbox transaccional + jobs sync catálogo).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${NODO_DIR}/venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "No se encontro ${VENV_PYTHON}. Cree el venv e instale requirements.txt." >&2
  exit 1
fi

cd "${NODO_DIR}"
exec "${VENV_PYTHON}" -m huey.bin.huey_consumer huey_tasks.huey
