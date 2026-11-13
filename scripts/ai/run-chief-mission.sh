#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${HOME}/.config/streamiov"
for env_file in "${CONFIG_DIR}/ai-worker.env" "${CONFIG_DIR}/ai-chief.env"; do
  if [[ -f "${env_file}" ]]; then
    # These files are private local configuration, never committed to the repository.
    source "${env_file}"
  fi
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
MISSION_ID="${STREAMIOV_AI_MISSION_ID:-}"
MISSION_DB="${STREAMIOV_AI_MISSION_DB:-${PROJECT_ROOT}/.streamiov/ai-missions.sqlite3}"

if [[ -z "${MISSION_ID}" ]]; then
  echo "STREAMIOV_AI_MISSION_ID is missing. Set it in ~/.config/streamiov/ai-chief.env." >&2
  exit 2
fi

cd "${PROJECT_ROOT}"
exec python3 -m ai \
  --project-root "${PROJECT_ROOT}" \
  --mission-db "${MISSION_DB}" \
  --mission-run "${MISSION_ID}"
