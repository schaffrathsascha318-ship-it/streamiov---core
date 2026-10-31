"""Prepare the active Electron Studio UI before launch or packaging.

The repository keeps the current Regie UI as regie-v2.html. Electron's main
process loads index.html, so this script creates that runtime entry point
atomically and refuses to follow or replace a symlink.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "streamiov-studio-app"
SOURCE = APP / "regie-v2.html"
TARGET = APP / "index.html"


def main() -> int:
    if not SOURCE.is_file() or SOURCE.is_symlink():
        raise SystemExit(f"Studio UI source is missing or unsafe: {SOURCE}")
    if TARGET.is_symlink():
        raise SystemExit(f"Refusing to replace a symlink: {TARGET}")

    payload = SOURCE.read_bytes()
    if not payload.strip():
        raise SystemExit("Studio UI source is empty.")

    fd, temporary_name = tempfile.mkstemp(
        prefix=".index.html.",
        suffix=".tmp",
        dir=APP,
    )
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

    print(f"Prepared Electron entry point: {TARGET.relative_to(ROOT)} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
