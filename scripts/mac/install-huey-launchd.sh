#!/usr/bin/env bash
# Registra consumer Huey del nodo en LaunchAgents (usuario actual).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LABEL="com.multishop.nodo-huey"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
START_SCRIPT="${NODO_DIR}/scripts/start-huey-consumer.sh"
LOG_DIR="${NODO_DIR}/data"
OUT_LOG="${LOG_DIR}/huey-launchd.out.log"
ERR_LOG="${LOG_DIR}/huey-launchd.err.log"

if [[ ! -x "${START_SCRIPT}" ]]; then
  chmod +x "${START_SCRIPT}"
fi

mkdir -p "${LOG_DIR}" "${HOME}/Library/LaunchAgents"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl unload "${PLIST_PATH}" 2>/dev/null || true

cat >"${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${START_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${NODO_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${OUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "Huey consumer LaunchAgent: ${PLIST_PATH}"
echo "Logs: ${OUT_LOG} / ${ERR_LOG}"
echo "Estado: launchctl print gui/$(id -u)/${LABEL}"
