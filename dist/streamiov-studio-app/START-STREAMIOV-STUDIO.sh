#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x node_modules/.bin/electron ]; then
  echo "Electron fehlt. Bitte zuerst im App-Ordner npm install ausführen."
  read -r -p "Enter zum Schließen..."
  exit 1
fi
exec ./node_modules/.bin/electron . --disable-gpu --disable-gpu-compositing
