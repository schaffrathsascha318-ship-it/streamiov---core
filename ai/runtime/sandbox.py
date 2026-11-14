"""Fail-closed Bubblewrap runner for untrusted project tests."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_FILES = 20000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024

ALLOWED_DIRS = {
    "ai", "games", "host", "modules", "scripts",
    "tests", "core", "docs",
}
DENIED_NAMES = {
    ".git", ".wrangler", "node_modules", "__pycache__",
    ".venv", "venv", ".tox", ".ssh", "secrets", "oauth",
    "db", "backups", "connector",
}
DENIED_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".sqlite",
    ".sqlite3", ".db", ".pyc",
}
DENIED_WORDS = ("secret", "credential", "access-token", "refresh-token")


def _safe_name(name: str) -> bool:
    lower = name.lower()
    return (
        lower not in DENIED_NAMES
        and not lower.startswith(".env")
        and not any(word in lower for word in DENIED_WORDS)
        and Path(lower).suffix not in DENIED_SUFFIXES
    )


def _copy_tree(source: Path, target: Path, state: dict) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda p: p.name.lower()):
        if not _safe_name(item.name) or item.is_symlink():
            continue
        if item.is_dir():
            _copy_tree(item, target / item.name, state)
            continue
        if not item.is_file():
            continue
        size = item.stat().st_size
        if size > MAX_FILE_BYTES:
            continue
        state["files"] += 1
        state["bytes"] += size
        if state["files"] > MAX_FILES or state["bytes"] > MAX_TOTAL_BYTES:
            raise RuntimeError("Sandbox snapshot exceeds its file or size limit.")
        shutil.copy2(item, target / item.name)


def create_snapshot(root: Path, destination: Path) -> None:
    """Copy only approved source trees and safe root-level files."""
    root = root.resolve()
    state = {"files": 0, "bytes": 0}

    for name in sorted(ALLOWED_DIRS):
        source = root / name
        if source.is_dir() and not source.is_symlink():
            _copy_tree(source, destination / name, state)

    # Include safe application fixtures, never root-level user or streamer data.
    data = root / "data"
    if data.is_dir() and not data.is_symlink():
        for name in (
            "game_actions", "games", "gaming_studio",
            "gift-gallery", "music", "overlays", "stickers",
        ):
            source = data / name
            if source.is_dir() and not source.is_symlink():
                _copy_tree(source, destination / "data" / name, state)

    # Include the Cloudflare worker configuration and CI workflows.
    for relative in (
        Path(".github") / "workflows",
        Path("infrastructure") / "cloudflare" / "streamiov-ai-worker",
    ):
        source = root / relative
        if source.is_dir() and not source.is_symlink():
            _copy_tree(source, destination / relative, state)

    # Build output is useful for Studio and homepage checks, but dependencies
    # are deliberately excluded by the recursive deny-list.
    dist = root / "dist"
    if dist.is_dir() and not dist.is_symlink():
        for name in ("streamiov-studio-app", "streamiov-homepage-worker"):
            source = dist / name
            if source.is_dir() and not source.is_symlink():
                _copy_tree(source, destination / "dist" / name, state)

    for item in root.iterdir():
        if item.is_file() and not item.is_symlink() and _safe_name(item.name):
            size = item.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            state["files"] += 1
            state["bytes"] += size
            if state["files"] > MAX_FILES or state["bytes"] > MAX_TOTAL_BYTES:
                raise RuntimeError("Sandbox snapshot exceeds its file or size limit.")
            shutil.copy2(item, destination / item.name)


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def run_sandboxed(root: Path, argv: list[str], timeout: float):
    """Run a fixed argv in an isolated, networkless, disposable workspace."""
    if not argv or not all(isinstance(part, str) and part for part in argv):
        raise RuntimeError("Invalid sandbox command.")

    # Nested specialist checks inherit the already-established outer sandbox.
    if os.environ.get("STREAMIOV_SANDBOX") == "1":
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "PYTHONPATH": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            "STREAMIOV_SANDBOX": "1",
        }
        try:
            return subprocess.run(
                argv, cwd=root, capture_output=True, text=True,
                timeout=timeout, check=False, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            err = exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", "replace")
            return _completed(124, out, err + "\nNested sandbox test timed out.")

    bwrap = shutil.which("bwrap")
    prlimit = shutil.which("prlimit")
    if not bwrap or not prlimit:
        raise RuntimeError("Bubblewrap and prlimit are required; refusing host execution.")

    node_host = None
    if argv[0] == "node":
        node_host = shutil.which("node")
        if not node_host:
            raise RuntimeError("Node.js is required but unavailable.")

    try:
        with tempfile.TemporaryDirectory(prefix="streamiov-test-sandbox-") as temp:
            stage = Path(temp) / "workspace"
            stage.mkdir()
            create_snapshot(root, stage)

            bwrap_args = [
                bwrap,
                "--unshare-all",
                "--unshare-user",
                "--disable-userns",
                "--assert-userns-disabled",
                "--die-with-parent",
                "--new-session",
                "--ro-bind", "/usr", "/usr",
                "--symlink", "usr/lib", "/lib",
                "--proc", "/proc",
                "--dev", "/dev",
                "--size", "134217728",
                "--tmpfs", "/tmp",
                "--dir", "/workspace",
                "--bind", str(stage), "/workspace",
            ]

            # Expose only the linker cache and required numerical libraries.
            # Do not mount the complete host /etc directory.
            ld_cache = Path("/etc/ld.so.cache")
            if ld_cache.is_file():
                bwrap_args.extend([
                    "--dir", "/etc",
                    "--dir", "/etc/alternatives",
                    "--ro-bind", str(ld_cache), "/etc/ld.so.cache",
                ])

                for library in ("blas", "lapack"):
                    alternative = Path(
                        f"/etc/alternatives/lib{library}.so.3-aarch64-linux-gnu"
                    )
                    if alternative.exists():
                        resolved = alternative.resolve(strict=True)
                        if resolved.is_file():
                            bwrap_args.extend([
                                "--ro-bind", str(resolved), str(alternative),
                            ])

            if node_host:
                node_host = str(Path(node_host).resolve(strict=True))
                if not Path(node_host).is_file():
                    raise RuntimeError("Node.js executable is not a regular file.")
                node_placeholder = stage / ".sandbox-bin" / "node"
                node_placeholder.parent.mkdir(parents=True, exist_ok=True)
                node_placeholder.touch()
                bwrap_args.extend([
                    "--ro-bind", node_host, "/workspace/.sandbox-bin/node",
                ])
                path_value = "/workspace/.sandbox-bin:/usr/bin"
            else:
                path_value = "/usr/bin"

            bwrap_args.extend([
                "--clearenv",
                "--setenv", "PATH", path_value,
                "--setenv", "PYTHONPATH", "/workspace",
                "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                "--setenv", "PYTHONNOUSERSITE", "1",
                "--setenv", "PYTHONUTF8", "1",
                "--setenv", "LC_ALL", "C.UTF-8",
                "--setenv", "STREAMIOV_SANDBOX", "1",
                "--chdir", "/workspace",
                prlimit,
                "--cpu=180:180",
                "--fsize=52428800:52428800",
                "--nofile=128:128",
                "--nproc=64:64",
                "--",
                *argv,
            ])

            try:
                return subprocess.run(
                    bwrap_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 10,
                    check=False,
                    env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                )
            except subprocess.TimeoutExpired as exc:
                out = exc.stdout or ""
                err = exc.stderr or ""
                if isinstance(out, bytes):
                    out = out.decode("utf-8", "replace")
                if isinstance(err, bytes):
                    err = err.decode("utf-8", "replace")
                return _completed(124, out, err + "\nSandbox test timed out.")
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"Sandbox setup failed; no host fallback: {exc}") from exc
