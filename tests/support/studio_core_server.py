"""Local Core helper used by the Studio integration tests."""

from __future__ import annotations

import os
import signal
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from host.auth import AuthStore
from host.server import Handler, StreamioVHTTPServer


def main() -> int:
    public = ROOT / "dist" / "streamiov-homepage-worker" / "public"
    temporary = tempfile.TemporaryDirectory(prefix="streamiov-studio-core-")
    os.environ.setdefault("STREAMIOV_TOKEN_KEY", "studio-integration-token-key-0123456789")
    data_dir = Path(temporary.name)
    username = os.environ.get("STREAMIOV_TEST_USERNAME")
    password = os.environ.get("STREAMIOV_TEST_PASSWORD")
    if username and password:
        AuthStore(data_dir).register(username, password)
    server = StreamioVHTTPServer(
        ("127.0.0.1", 0), Handler, public, data_dir,
        registration_open=False,
    )

    def stop(_signum=None, _frame=None) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    print(str(server.server_address[1]), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
