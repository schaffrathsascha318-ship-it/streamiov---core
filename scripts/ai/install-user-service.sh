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
# Set the mission ID printed by: python3 -m ai --mission-create --task "..."
STREAMIOV_AI_MISSION_ID=
# Optional:
# STREAMIOV_AI_MISSION_DB=/absolute/path/to/.streamiov/ai-missions.sqlite3
EOF
  chmod 600 "${HOME}/.config/streamiov/ai-chief.env"
  echo "Created ~/.config/streamiov/ai-chief.env. Set STREAMIOV_AI_MISSION_ID, then rerun this installer."
  exit 2
fi

if ! grep -Eq '^STREAMIOV_AI_MISSION_ID=.+$' "${HOME}/.config/streamiov/ai-chief.env"; then
  echo "Set STREAMIOV_AI_MISSION_ID in ~/.config/streamiov/ai-chief.env before installing." >&2
  exit 2
fi

mkdir -p "${UNIT_DIR}"
WORKDIR_ESCAPED="$(systemd-escape --path "${PROJECT_ROOT}")"
RUNNER_ESCAPED="$(systemd-escape --path "${RUNNER}")"
cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=Streamiov AI Chief Developer mission runner
After=default.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=${WORKDIR_ESCAPED}
ExecStart=/bin/bash ${RUNNER_ESCAPED}
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
