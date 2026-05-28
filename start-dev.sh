#!/usr/bin/env bash
# Atajo desde la raíz del agente → scripts/mac/start-dev.sh
# Uso: ./start-dev.sh [--bundle-dir DIR] [--no-wg] [--skip-triggers] [--skip-docker]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${ROOT}/scripts/mac/start-dev.sh" "$@"
