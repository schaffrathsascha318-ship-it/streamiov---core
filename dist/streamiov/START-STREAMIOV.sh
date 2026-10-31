#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if command -v python3 >/dev/null 2>&1; then
  echo "Streamiov Studio wird gestartet..."
  python3 -m http.server 8766 --bind 127.0.0.1 >/tmp/streamiov-studio.log 2>&1 &
  PID=$!
  trap 'kill "$PID" 2>/dev/null || true' EXIT
  sleep 1

  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:8766/streamiov-studio.html" >/dev/null 2>&1 || true
  fi

  echo "Streamiov Studio: http://127.0.0.1:8766/streamiov-studio.html"
  wait "$PID"
else
  echo "Python 3 wird zum Starten des integrierten Studios benötigt."
  exit 1
fi
