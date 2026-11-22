#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/dist/streamiov-studio-app"

fail() {
  printf 'STREAMIOV-SETUP-FEHLER: %s\n' "$*" >&2
  exit 1
}

command -v node >/dev/null 2>&1 || fail "Node.js 22.12 oder neuer fehlt. Bitte Node.js installieren und erneut starten."
command -v npm >/dev/null 2>&1 || fail "npm fehlt. Bitte Node.js 22.12 oder neuer installieren."

node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 12)) process.exit(1)' \
  || fail "Gefundenes Node.js ist zu alt: $(node --version). Benötigt wird mindestens 22.12.0."

command -v python3 >/dev/null 2>&1 || fail "Python 3 fehlt. Die Studio-Vorbereitung benötigt Python 3."
[[ -f "$APP_DIR/package-lock.json" ]] || fail "Studio-Paket oder package-lock.json fehlt: $APP_DIR"

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    printf 'FFmpeg fehlt. Installiere das kostenlose Debian-Paket (sudo erforderlich) …\n'
    sudo apt-get update
    sudo apt-get install -y ffmpeg
  else
    fail "FFmpeg fehlt. Auf Debian/Crostini: sudo apt-get update && sudo apt-get install -y ffmpeg"
  fi
fi

command -v ffmpeg >/dev/null 2>&1 || fail "FFmpeg ist nach der Paketinstallation weiterhin nicht auffindbar."
encoders="$(ffmpeg -hide_banner -encoders 2>/dev/null || true)"
protocols="$(ffmpeg -hide_banner -protocols 2>/dev/null || true)"
missing=()
grep -Eq '[[:space:]]libx264([[:space:]]|$)' <<<"$encoders" || missing+=("libx264")
grep -Eq '[[:space:]]aac([[:space:]]|$)' <<<"$encoders" || missing+=("AAC")
grep -Eq '^[[:space:]]*rtmp(s)?[[:space:]]*$' <<<"$protocols" || missing+=("RTMP/RTMPS")
if (("${#missing[@]}" > 0)); then
  printf 'FFmpeg ist vorhanden, aber erforderliche Funktionen fehlen: %s\n' "${missing[*]}" >&2
  fail "Bitte eine FFmpeg-Version mit libx264, AAC und RTMP/RTMPS bereitstellen. Die vorhandene Installation wurde nicht ersetzt."
fi

printf '\n[1/3] Installiere exakt gesperrte Studio-Abhängigkeiten …\n'
cd "$APP_DIR"
npm ci

printf '\n[2/3] Prüfe die Streamiov-eigene Regie-Engine …\n'
npm run test:engine

printf '\n[3/3] Starte Streamiov Studio lokal …\n'
exec npm start -- --disable-gpu --disable-gpu-compositing
