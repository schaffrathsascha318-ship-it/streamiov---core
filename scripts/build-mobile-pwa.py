#!/usr/bin/env python3
"""Build the installable STREAMIOV web Regie from the canonical Studio UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dist/streamiov-studio-app/regie-v2.html"
TARGET = ROOT / "dist/streamiov-homepage-worker/public/app/index.html"

HEAD_MARKER = "<head>"
BODY_MARKER = "</body>"
PWA_HEAD = """
<meta name="theme-color" content="#090d13">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="STREAMIOV">
<link rel="manifest" href="/app/manifest.webmanifest">
<link rel="icon" href="/app/icon.svg" type="image/svg+xml">
"""
PWA_RUNTIME = """
<div id="streamiov-web-runtime-notice" role="status" aria-live="polite"
 style="position:relative;z-index:20;padding:9px 14px;background:#241f3b;border-bottom:1px solid #7c70ff;color:#eeeaff;font-size:12px;text-align:center">
 STREAMIOV WEB-REGIE · Geräte- und Medienfunktionen hängen von Browser, Berechtigungen und verbundenem Core ab. LIVE-Ausgabe ist hier nicht als aktiv bestätigt.
</div>
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/app/sw.js', { scope: '/app/' }).catch(() => {});
  });
}
</script>
"""

def main():
    if not SOURCE.is_file():
        raise SystemExit(f"Canonical Studio UI missing: {SOURCE}")
    html = SOURCE.read_text(encoding="utf-8")
    if HEAD_MARKER not in html or BODY_MARKER not in html:
        raise SystemExit("Canonical Studio UI has no expected HTML document structure")
    html = html.replace(HEAD_MARKER, HEAD_MARKER + PWA_HEAD, 1)
    html = html.replace(BODY_MARKER, PWA_RUNTIME + BODY_MARKER, 1)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(html, encoding="utf-8")
    print(f"Built installable web Regie: {TARGET}")

if __name__ == "__main__":
    main()
