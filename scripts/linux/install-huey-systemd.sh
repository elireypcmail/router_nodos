#!/usr/bin/env bash
# Instala unidad systemd para el consumer Huey del nodo (requiere sudo).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
UNIT_NAME="multishop-nodo-huey.service"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"
START_SCRIPT="${NODO_DIR}/scripts/start-huey-consumer.sh"

if [[ ! -x "${START_SCRIPT}" ]]; then
  chmod +x "${START_SCRIPT}"
fi

sudo tee "${UNIT_PATH}" >/dev/null <<EOF
[Unit]
Description=Multishop nodo Huey consumer (outbox movimientos → router webhooks)
After=network-online.target mysql.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${NODO_DIR}
ExecStart=${START_SCRIPT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${UNIT_NAME}"
sudo systemctl restart "${UNIT_NAME}"
echo "Huey consumer: systemctl status ${UNIT_NAME}"
