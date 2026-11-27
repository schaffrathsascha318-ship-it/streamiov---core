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
if [[ -z "${STREAMIOV_MODEL_URL:-}" && -n "${OLLAMA_HOST:-}" ]]; then
  export STREAMIOV_MODEL_URL="${OLLAMA_HOST}"
fi
if [[ -z "${STREAMIOV_MODEL_URL:-}" && -n "${OLLAMA_API_BASE:-}" ]]; then
  export STREAMIOV_MODEL_URL="${OLLAMA_API_BASE}"
fi
PROJECT_GOAL="${STREAMIOV_PROJECT_GOAL:-${STREAMIOV_AI_PROJECT_GOAL:-Continue the final STREAMIOV completion mission. Make the complete AI infrastructure, all 17 named AI agents, real tools, integrations, capabilities, tests, builds and autonomous operation demonstrably ready. Use real tools and observed results only; never simulate progress. Prioritize independently verified unfinished objectives, repair failures promptly, and preserve credentials, OAuth identities, user data, encrypted mission state, protected control-plane paths and production safeguards.}}"
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
