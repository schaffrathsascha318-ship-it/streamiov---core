#!/usr/bin/env python3
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(ROOT / "scripts/build-mobile-pwa.py")], check=True)
app = ROOT / "dist/streamiov-homepage-worker/public/app"
html = (app / "index.html").read_text(encoding="utf-8")
manifest = json.loads((app / "manifest.webmanifest").read_text(encoding="utf-8"))
worker = (app / "sw.js").read_text(encoding="utf-8")
assert manifest["start_url"] == "/app/"
assert manifest["scope"] == "/app/"
assert manifest["display"] == "standalone"
assert "/app/manifest.webmanifest" in html
assert "serviceWorker.register('/app/sw.js'" in html
assert "LIVE-Ausgabe ist hier nicht als aktiv bestätigt" in html
assert "streamiov-web-regie-v1" in worker
assert (app / "icon.svg").is_file()
print("PASS: install manifest, generated shared Regie, offline shell and honest LIVE boundary")
