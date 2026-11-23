#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
RUNNER="${PROJECT_ROOT}/scripts/ai/run-chief-mission.sh"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/streamiov-ai-chief.service"

if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
  cat >&2 <<'EOF'
A working systemd user manager is not available in this Linux session.
No service files were changed. Start the mission manually with:
  bash scripts/ai/run-chief-mission.sh
On systems that support user services, enable the user manager and rerun this installer.
EOF
  exit 1
fi

if [[ ! -f "${HOME}/.config/streamiov/ai-chief.env" ]]; then
  mkdir -p "${HOME}/.config/streamiov"
  cat > "${HOME}/.config/streamiov/ai-chief.env" <<'EOF'
# Optional: override the persistent whole-platform development goal.
# STREAMIOV_AI_PROJECT_GOAL="Continue building and verifying the complete Streamiov platform."
# Optional: adopt an existing mission checkpoint on first supervisor start.
STREAMIOV_AI_MISSION_ID=
# Optional:
# STREAMIOV_AI_MISSION_DB=/absolute/path/to/.streamiov/ai-missions.sqlite3
EOF
  chmod 600 "${HOME}/.config/streamiov/ai-chief.env"
fi

mkdir -p "${UNIT_DIR}"
if [[ "${PROJECT_ROOT}" == *" "* || "${RUNNER}" == *" "* ]]; then
  echo "Project paths containing spaces are not supported by this installer." >&2
  exit 1
fi
cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=Streamiov AI Chief Developer mission runner
After=default.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=${PROJECT_ROOT}
ExecStart=/bin/bash ${RUNNER}
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now streamiov-ai-chief.service
echo "Streamiov AI Chief user service installed and started."
echo "Status: systemctl --user status streamiov-ai-chief.service"
echo "Logs:   journalctl --user -u streamiov-ai-chief.service -f"
