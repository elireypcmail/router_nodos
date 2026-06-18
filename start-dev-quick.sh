#!/usr/bin/env bash
# Igual que start-dev.sh pero sin crear venv ni pip install (paso 2).
# Requiere haber ejecutado ./start-dev.sh al menos una vez.
# Uso: ./start-dev-quick.sh [--bundle-dir DIR] [--no-wg] [--skip-triggers] [--skip-docker]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${ROOT}/scripts/mac/start-dev.sh" --skip-venv "$@"
