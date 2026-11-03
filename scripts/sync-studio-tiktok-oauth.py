"""Sync the canonical TikTok OAuth service into the Electron app package."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "core" / "integration" / "tiktok-oauth.js"
APP = ROOT / "dist" / "streamiov-studio-app"
TARGET = APP / "tiktok-oauth.js"


def main() -> int:
    if not SOURCE.is_file() or SOURCE.is_symlink():
        raise SystemExit(f"Canonical OAuth service is missing or unsafe: {SOURCE}")
    APP.mkdir(parents=True, exist_ok=True)
    payload = SOURCE.read_bytes()
    if not payload.strip():
        raise SystemExit("Canonical OAuth service is empty.")
    fd, temporary_name = tempfile.mkstemp(prefix=".tiktok-oauth.", suffix=".tmp", dir=APP)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, TARGET)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    print(f"Prepared packaged OAuth service: {TARGET.relative_to(ROOT)} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
