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
PROJECT_GOAL="${STREAMIOV_AI_PROJECT_GOAL:-Continue building and independently verifying the complete Streamiov platform. Prioritize the reliable AI Chief, Core, the standalone Studio, separate TikTok LIVE and Twitch LIVE integrations, real audio/video production, creator tools, original games, and safe releases. Continue with the highest-value unfinished objective after every independently verified mission. Repair failures promptly, avoid repeating verified work, and preserve credentials, OAuth identities, user data, encrypted mission state, and production safeguards.}"
MISSION_ID="${STREAMIOV_AI_MISSION_ID:-}"
MISSION_DB="${STREAMIOV_AI_MISSION_DB:-${PROJECT_ROOT}/.streamiov/ai-missions.sqlite3}"

cd "${PROJECT_ROOT}"
ARGS=(
  --project-root "${PROJECT_ROOT}"
  --mission-db "${MISSION_DB}"
  --project-supervisor-run
  --task "${PROJECT_GOAL}"
  --full-project-development
)
if [[ -n "${MISSION_ID}" ]]; then
  ARGS+=(--project-supervisor-adopt-mission "${MISSION_ID}")
fi
exec python3 -m ai "${ARGS[@]}"
