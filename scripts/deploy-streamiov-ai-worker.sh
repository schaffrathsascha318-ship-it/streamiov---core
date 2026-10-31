#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ABBRUCH: Bitte das Streamiov-Repository ausführen." >&2
  exit 2
}
cd "$ROOT"

CONFIG="infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc"
LOCAL_CONFIG_DIR="${HOME}/.config/streamiov"
LOCAL_ENV="${LOCAL_CONFIG_DIR}/ai-worker.env"

for command_name in git npx openssl curl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "ABBRUCH: Benötigtes Programm fehlt: $command_name" >&2
    exit 2
  }
done

[[ -f "$CONFIG" ]] || {
  echo "ABBRUCH: Worker-Konfiguration fehlt: $CONFIG" >&2
  exit 2
}

echo "=== Cloudflare-Anmeldung prüfen ==="
npx --yes wrangler@4 whoami

umask 077
mkdir -p "$LOCAL_CONFIG_DIR"
TOKEN="$(openssl rand -hex 32)"

echo "=== Streamiov AI Worker erstmalig bereitstellen ==="
DEPLOY_OUTPUT="$(npx --yes wrangler@4 deploy --config "$CONFIG" 2>&1)" || {
  printf '%s\n' "$DEPLOY_OUTPUT" >&2
  echo "ABBRUCH: Worker konnte nicht bereitgestellt werden." >&2
  exit 3
}
printf '%s\n' "$DEPLOY_OUTPUT"
WORKER_URL="$(printf '%s\n' "$DEPLOY_OUTPUT" | grep -Eo 'https://[^[:space:]]+\.workers\.dev' | tail -n 1 || true)"

if [[ -z "$WORKER_URL" ]]; then
  echo "ABBRUCH: Wrangler hat keine workers.dev-URL ausgegeben. Worker-URL im Cloudflare-Dashboard prüfen." >&2
  exit 4
fi

cat > "$LOCAL_ENV" <<EOF
export STREAMIOV_MODEL_PROVIDER=cloudflare-workers-ai
export STREAMIOV_MODEL=@cf/zai-org/glm-4.7-flash
export STREAMIOV_MODEL_URL=$WORKER_URL
export STREAMIOV_AI_WORKER_TOKEN=$TOKEN
EOF
chmod 600 "$LOCAL_ENV"

echo "=== Separates Zugriffstoken als Cloudflare Secret setzen ==="
printf '%s' "$TOKEN" | npx --yes wrangler@4 secret put STREAMIOV_AI_WORKER_TOKEN --config "$CONFIG"

echo "=== Worker mit Secret aktualisieren ==="
npx --yes wrangler@4 deploy --config "$CONFIG"

echo "=== Authentifizierten Health-Check ausführen ==="
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl --fail --silent --show-error --config - "$WORKER_URL/health"
echo
echo
echo "ERFOLG: Streamiov AI Worker ist erreichbar."
echo "Worker: $WORKER_URL"
echo "Lokale Konfiguration: $LOCAL_ENV (Dateirechte 600)"
echo "Agent starten: source \"$LOCAL_ENV\" && python -m ai --doctor"
echo "Das Zugriffstoken wurde nicht ausgegeben."
