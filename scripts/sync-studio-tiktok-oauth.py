"""Sync canonical TikTok OAuth and Display API adapters into the sandbox Electron app."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "streamiov-studio-app"
FILES = (
    (ROOT / "core" / "integration" / "tiktok-oauth.js", APP / "tiktok-oauth.js"),
    (ROOT / "core" / "integration" / "tiktok-display-api.js", APP / "tiktok-display-api.js"),
)


def sync_file(source: Path, target: Path) -> int:
    if not source.is_file() or source.is_symlink():
        raise SystemExit(f"Canonical TikTok service is missing or unsafe: {source}")
    payload = source.read_bytes()
    if not payload.strip():
        raise SystemExit(f"Canonical TikTok service is empty: {source}")
    fd, temporary_name = tempfile.mkstemp(prefix=".tiktok-service.", suffix=".tmp", dir=APP)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    print(f"Prepared packaged TikTok service: {target.relative_to(ROOT)} ({len(payload)} bytes)")
    return 0


def main() -> int:
    APP.mkdir(parents=True, exist_ok=True)
    for source, target in FILES:
        sync_file(source, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
