"""Constrained project tools: safe file access and fixed test commands only."""
from __future__ import annotations
import os
import ctypes
import hashlib
import json
import stat
import shutil
import subprocess
import sys
import time
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

class ToolError(RuntimeError):
    pass

DENIED_PARTS = {".git", ".github", ".env", ".wrangler", "node_modules", "__pycache__", "secrets", "oauth", ".ssh"}
DENIED_FILE_NAMES = {"auth.json", "oauth.json", "token.json", "tokens.json", "credentials.json", "client_secret.json", "tiktok-oauth.js"}
DENIED_PATH_PREFIXES = {"scripts/autonomous"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
PROTECTED_WRITE_PREFIXES = (
    "ai/providers/",
    ".github/workflows/",
    ".github/actions/",
    "scripts/autonomous/",
    "scripts/ai/",
    "infrastructure/",
)
PROTECTED_WRITE_FILES = {
    "ai/__main__.py",
    "ai/core/agent.py",
    "ai/runtime/continuous_engine.py",
    "ai/runtime/project_tools.py",
    "host/auth.py",
    "scripts/release-signing.mjs",
    "scripts/build-ffmpeg-source-bundle.py",
}
CHIEF_CORE_FILES = frozenset({
    "ai/__main__.py",
    "ai/core/agent.py",
    "ai/runtime/continuous_engine.py",
    "ai/runtime/project_tools.py",
})
SELF_MODIFIABLE_CORE_FILES = CHIEF_CORE_FILES
PROTECTED_WRITE_NAMES = {
    "wrangler.jsonc",
    "wrangler.toml",
    "dockerfile",
    "procfile",
    "app.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "fly.toml",
    "netlify.toml",
    "render.yaml",
    "vercel.json",
}
TEST_COMMANDS = {
    "python -m unittest discover -s tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
    "python scripts/verify-cloudflare-config.py": [sys.executable, "scripts/verify-cloudflare-config.py"],
}
NODE_TEST_COMMANDS = {
    "node --test tests/test_cloudflare_ai_worker.mjs": ["--test", "tests/test_cloudflare_ai_worker.mjs"],
    "node scripts/release-signing.mjs verify-release": ["scripts/release-signing.mjs", "verify-release"],
}
MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 100

# Thread locks protect instances in one process; OS file locks extend the
# same guarantee to separate processes sharing this checkout on the same host.
# Lock files live outside the repository and are released by the OS on process exit.
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_LOCK_TIMEOUT_SECONDS = 300

try:
    import fcntl as _fcntl
except ImportError:  # Windows
    _fcntl = None
try:
    import msvcrt as _msvcrt
except ImportError:  # POSIX
    _msvcrt = None


def _harden_parent_process() -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl = getattr(libc, "prctl", None)
        if prctl is None:
            raise ToolError("Unable to lock down parent process before untrusted execution.")
        prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        prctl.restype = ctypes.c_int
        ctypes.set_errno(0)
        if prctl(4, 0, 0, 0, 0) != 0:
            raise ToolError(
                "Unable to lock down parent process before untrusted execution (errno "
                + str(ctypes.get_errno()) + ")."
            )
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("Unable to lock down parent process before untrusted execution: " + str(exc)) from exc


def _sandboxed_test_command(root: Path, argv: list[str]) -> tuple[list[str], dict[str, str]]:
    bwrap = shutil.which("bwrap") if os.name == "posix" else None
    if bwrap is None:
        raise ToolError(
            "Safe test execution requires bubblewrap with a read-only host bind; "
            "unsandboxed test execution is disabled."
        )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(root),
    }
    command = [
        bwrap, "--unshare-user", "--unshare-net", "--die-with-parent",
        "--uid", "65534", "--gid", "65534",
        "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--chdir", str(root), "--", *argv,
    ]
    return command, env


def _process_lock_path(key: str) -> Path:
    user_scope = str(getattr(os, "getuid", lambda: os.environ.get("USERNAME", "default"))())
    scope = hashlib.sha256(user_scope.encode("utf-8")).hexdigest()[:16]
    root = Path(tempfile.gettempdir()) / ("streamiov-path-locks-" + scope)
    if root.is_symlink():
        raise ToolError("Cross-process lock directory must not be a symlink.")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ToolError("Cross-process lock directory is unsafe.")
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    digest = hashlib.sha256(os.path.normcase(key).encode("utf-8")).hexdigest()
    return root / (digest + ".lock")


def _acquire_process_lock(descriptor: int) -> None:
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    if _fcntl is not None:
        while True:
            try:
                _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ToolError("Timed out waiting for another process to release this file.")
                time.sleep(0.05)
    elif _msvcrt is not None:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\\0")
        while True:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                _msvcrt.locking(descriptor, _msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise ToolError("Timed out waiting for another process to release this file.")
                time.sleep(0.05)
    else:
        raise ToolError("No supported OS file-lock provider is available; refusing an unlocked write.")


def _release_process_lock(descriptor: int) -> None:
    if _fcntl is not None:
        _fcntl.flock(descriptor, _fcntl.LOCK_UN)
    elif _msvcrt is not None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)


@contextmanager
def _locked_path(path: Path, *, owner: dict | None = None):
    key = str(path.resolve(strict=False))
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.setdefault(key, threading.RLock())
    with lock:
        lock_path = _process_lock_path(key)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if lock_path.is_symlink():
            raise ToolError("Cross-process lock file must not be a symlink.")
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise ToolError("Could not open a safe cross-process file lock.") from exc
        acquired = False
        try:
            path_info = lock_path.lstat()
            file_info = os.fstat(descriptor)
            if (not stat.S_ISREG(path_info.st_mode) or not stat.S_ISREG(file_info.st_mode)
                    or (path_info.st_dev, path_info.st_ino) != (file_info.st_dev, file_info.st_ino)):
                raise ToolError("Cross-process lock is not a stable regular file.")
            try:
                os.chmod(lock_path, 0o600)
            except OSError:
                pass
            _acquire_process_lock(descriptor)
            acquired = True
            metadata = {
                "pid": os.getpid(),
                "task_id": str((owner or {}).get("task_id") or "process:" + str(os.getpid()))[:128],
                "path_sha256": hashlib.sha256(key.encode("utf-8")).hexdigest(),
                "acquired_at": time.time(),
            }
            encoded = json.dumps(metadata, sort_keys=True).encode("utf-8")
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, encoded)
            os.fsync(descriptor)
            yield
        finally:
            try:
                if acquired:
                    _release_process_lock(descriptor)
            finally:
                os.close(descriptor)


def _atomic_replace_text(target: Path, content: str) -> None:
    """Replace a file atomically in its own directory; never expose partial text."""
    descriptor, temporary = tempfile.mkstemp(prefix=".streamiov-write-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            os.chmod(temporary, target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class ProjectTools:
    def __init__(
        self,
        root: str | Path,
        writable_prefixes: tuple[str, ...] = ("ai/", "docs/ai-development/", "tests/"),
        *,
        allow_game_checks: bool = False,
        allow_self_modification: bool = False,
        full_project_development: bool = False,
        task_id: str | None = None,
    ) -> None:
        if task_id is not None and (not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128 or "\\x00" in task_id):
            raise ToolError("Task ID must be 1–128 characters.")
        self.task_id = task_id.strip() if task_id else "process:" + str(os.getpid())
        self.root = Path(root).resolve()
        self.writable_prefixes = ("*",) if full_project_development else writable_prefixes
        self.allow_game_checks = allow_game_checks
        self.allow_self_modification = allow_self_modification or full_project_development
        self.full_project_development = full_project_development
        self._read_only = False
        self.workspace_store = None
        self.workspace_task_id = None

    def set_read_only(self, enabled: bool) -> None:
        self._read_only = bool(enabled)

    def _is_protected_relative(self, relative: str) -> bool:
        rel = PurePosixPath(relative)
        lowered = [part.lower() for part in rel.parts]
        if any(
            part in DENIED_PARTS
            or part.startswith(".env")
            or any(word in part for word in ("secret", "credential", "access-token", "refresh-token"))
            for part in lowered
        ):
            return True
        if rel.name.lower() in DENIED_FILE_NAMES or rel.suffix.lower() in DENIED_SUFFIXES:
            return True
        normalized = rel.as_posix().lower()
        return any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in DENIED_PATH_PREFIXES
        )

    def _resolve(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ToolError("A valid relative project path is required.")
        rel = PurePosixPath(raw)
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise ToolError("Path must be a normalized relative path without traversal.")
        if self._is_protected_relative(rel.as_posix()):
            raise ToolError("Access to protected paths and secret-like files is denied.")
        candidate = self.root.joinpath(*rel.parts)
        anchor = candidate if candidate.exists() else candidate.parent
        resolved_anchor = anchor.resolve()
        if self.root != resolved_anchor and self.root not in resolved_anchor.parents:
            raise ToolError("Path escapes the project workspace.")
        if candidate.is_symlink():
            raise ToolError("Symlink access is denied.")
        return candidate

    def _writable_target(self, raw: str) -> tuple[Path, str]:
        if self._read_only:
            raise ToolError("This verification task is read-only; implementation files must not be edited.")
        target = self._resolve(raw)
        normalized = target.relative_to(self.root).as_posix()
        self_core_write = (
            self.allow_self_modification
            and normalized in SELF_MODIFIABLE_CORE_FILES
        )
        if (
            (normalized in PROTECTED_WRITE_FILES and not self_core_write)
            or target.name.lower() in PROTECTED_WRITE_NAMES
            or any(
                normalized.startswith(prefix)
                for prefix in PROTECTED_WRITE_PREFIXES
                if not (self.full_project_development and prefix == "ai/providers/")
            )
        ):
            raise ToolError("Protected permission, provider, deployment, and runner-control files require explicit owner approval.")
        if "*" not in self.writable_prefixes and not any(
            normalized.startswith(prefix) for prefix in self.writable_prefixes
        ):
            raise ToolError("Write path is outside the configured project scope.")
        return target, normalized

    def _begin_workspace_change(self, relative: str, base_sha256: str, content: str) -> None:
        if self.workspace_store is None or not self.workspace_task_id:
            return
        try:
            self.workspace_store.begin_change(self.workspace_task_id, relative, base_sha256, content)
        except Exception as exc:
            raise ToolError("Workspace change was rejected: " + str(exc)[:500]) from exc

    def _complete_workspace_change(self, relative: str, content: str) -> None:
        if self.workspace_store is None or not self.workspace_task_id:
            return
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        try:
            self.workspace_store.complete_change(self.workspace_task_id, relative, digest)
        except Exception as exc:
            raise ToolError("Workspace change could not be persisted: " + str(exc)[:500]) from exc

    def _cancel_workspace_change(self, relative: str, content: str) -> None:
        if self.workspace_store is None or not self.workspace_task_id:
            return
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        try:
            self.workspace_store.cancel_change(self.workspace_task_id, relative, digest)
        except Exception:
            pass

    def list_files(self, path: str = ".") -> str:
        """List a bounded set of safe immediate children inside the project workspace."""
        target = self.root if path == "." else self._resolve(path)
        if not target.is_dir():
            raise ToolError("Requested path is not a project directory.")
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            if child.is_symlink():
                continue
            relative = child.relative_to(self.root).as_posix()
            if self._is_protected_relative(relative):
                continue
            kind = "dir" if child.is_dir() else "file" if child.is_file() else "other"
            if kind == "other":
                continue
            entries.append(f"{kind} {child.name}")
            if len(entries) >= MAX_LIST_ENTRIES:
                break
        suffix = "\n[listing capped at 100 entries]" if len(entries) >= MAX_LIST_ENTRIES else ""
        return "\n".join(entries) + suffix if entries else "(directory is empty or contains only excluded entries)"

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        with _locked_path(target, owner={"task_id": self.task_id}):
            target = self._resolve(path)
            if not target.is_file():
                raise ToolError("Requested file does not exist or is not a regular file.")
            if target.stat().st_size > MAX_FILE_BYTES:
                raise ToolError("File exceeds the 200 KB read limit.")
            return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        target, normalized = self._writable_target(path)
        if not isinstance(content, str) or len(content.encode("utf-8")) > 100_000:
            raise ToolError("Content must be text no larger than 100 KB.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with _locked_path(target, owner={"task_id": self.task_id}):
            target, normalized = self._writable_target(path)
            if target.exists():
                raise ToolError("Refusing to overwrite an existing file; use an exact-match edit or submit a focused patch through review.")
            self._begin_workspace_change(normalized, "", content)
            descriptor, temporary = tempfile.mkstemp(prefix=".streamiov-create-", dir=target.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Hard-link creation is atomic and fails rather than replacing a
                # file created by another task after the existence check.
                os.link(temporary, target)
                self._complete_workspace_change(normalized, content)
            except FileExistsError:
                self._cancel_workspace_change(normalized, content)
                raise ToolError("Another task created this path concurrently; no file was overwritten.")
            except Exception:
                self._cancel_workspace_change(normalized, content)
                raise
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return f"Created {normalized} ({len(content)} characters)."

    def replace_text(self, path: str, old_text: str, new_text: str) -> str:
        """Apply one exact edit under a shared path lock and atomically publish it."""
        target, normalized = self._writable_target(path)
        if not isinstance(old_text, str) or not old_text:
            raise ToolError("old_text must be a non-empty string.")
        if not isinstance(new_text, str) or old_text == new_text:
            raise ToolError("new_text must be text different from old_text.")
        with _locked_path(target, owner={"task_id": self.task_id}):
            target, normalized = self._writable_target(path)
            if not target.is_file():
                raise ToolError("Exact-match edits require an existing regular file.")
            if target.stat().st_size > MAX_FILE_BYTES:
                raise ToolError("File exceeds the 200 KB edit limit.")
            original = target.read_text(encoding="utf-8")
            matches = original.count(old_text)
            if matches != 1:
                raise ToolError(f"Exact-match edit requires one occurrence; found {matches}. No change made.")
            updated = original.replace(old_text, new_text, 1)
            if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
                raise ToolError("Edited file would exceed the 200 KB limit.")
            self._begin_workspace_change(
                normalized, hashlib.sha256(original.encode("utf-8")).hexdigest(), updated,
            )
            try:
                _atomic_replace_text(target, updated)
                self._complete_workspace_change(normalized, updated)
            except Exception:
                self._cancel_workspace_change(normalized, updated)
                raise
        return f"Updated {normalized}: one exact match replaced."

    def run_python(self, path: str) -> str:
        """Run project Python in a read-only, unprivileged bubblewrap sandbox."""
        target = self._resolve(path)
        if target.suffix.lower() != ".py" or not target.is_file():
            raise ToolError("Python execution requires an existing .py file inside the project workspace.")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ToolError("Python source exceeds the 200 KB execution limit.")
        bwrap = shutil.which("bwrap") if os.name == "posix" else None
        if bwrap is None:
            raise ToolError(
                "Safe Python execution requires bubblewrap with a read-only host bind; "
                "unsandboxed execution is disabled."
            )
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": "",
            "PYTHONIOENCODING": "utf-8",
        }
        sandbox_command = [
            bwrap, "--unshare-user", "--unshare-net", "--die-with-parent",
            "--uid", "65534", "--gid", "65534",
            "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--chdir", str(self.root), "--", sys.executable, "-I", str(target),
        ]
        _harden_parent_process()
        result = subprocess.run(
            sandbox_command, cwd=self.root, capture_output=True, text=True,
            timeout=120, check=False, env=env,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return f"exit_code={result.returncode}\n{output[-12000:]}"

    def run_tests(self, command: str) -> str:
        if not isinstance(command, str):
            raise ToolError("Test command is not allowlisted.")
        argv = TEST_COMMANDS.get(command)
        if argv is None:
            node_args = NODE_TEST_COMMANDS.get(command)
            if node_args is None:
                raise ToolError("Test command is not allowlisted.")
            node = shutil.which("node")
            if node is None:
                raise ToolError("Node.js is required by this allowlisted test command but is not installed.")
            argv = [node, *node_args]
        argv, env = _sandboxed_test_command(self.root, argv)
        _harden_parent_process()
        result = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=180, check=False, env=env)
        output = (result.stdout + "\n" + result.stderr).strip()
        return f"exit_code={result.returncode}\n{output[-12000:]}"

    def run_game_checks(self) -> str:
        """Audit every local game package and run its discovered offline tests."""
        if not self.allow_game_checks:
            raise ToolError("The game check tool is available only to the games specialist.")
        releases = self.root / "games" / "releases"
        if not releases.is_dir() or releases.is_symlink():
            raise ToolError("The local games/releases directory is missing or unsafe.")
        manifests = []
        python_tests: set[str] = set()
        node_tests: set[str] = set()
        for project in sorted(releases.iterdir()):
            if project.is_symlink() or not project.is_dir():
                continue
            manifest = project / "manifest.json"
            if not manifest.exists():
                continue
            if manifest.is_symlink() or not manifest.is_file():
                raise ToolError("A game manifest path is unsafe.")
            manifest_relative = manifest.relative_to(self.root).as_posix()
            manifests.append(manifest_relative)
            test_root = project / "tests"
            if test_root.is_symlink():
                raise ToolError("A game test directory is unsafe.")
            if test_root.is_dir():
                for test_file in test_root.rglob("*"):
                    if test_file.is_symlink():
                        raise ToolError("Game test trees may not contain symlinks.")
                    if not test_file.is_file():
                        continue
                    relative = test_file.relative_to(self.root).as_posix()
                    if test_file.name.startswith("test_") and test_file.suffix == ".py":
                        python_tests.add(relative)
                    elif test_file.name.endswith(".test.cjs"):
                        node_tests.add(relative)
        if not manifests:
            raise ToolError("No local game manifests were found to audit.")

        commands = [
            ([sys.executable, "-m", "games.catalog", manifest], f"audit {manifest}")
            for manifest in manifests
        ]
        test_directories = sorted({str(PurePosixPath(path).parent) for path in python_tests})
        commands.extend(
            ([sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", "test_*.py"], f"Python game tests in {directory}")
            for directory in test_directories
        )
        if node_tests:
            node = shutil.which("node")
            if node is None:
                raise ToolError("Node.js is required by local game tests but is not installed.")
            commands.append(([node, "--test", *sorted(node_tests)], "Node game tests"))

        reports = []
        deadline = time.monotonic() + 180
        for argv, label in commands:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reports.append(f"{label}: total 180 second game-check limit reached")
                return "exit_code=124\n" + "\n\n".join(reports)[-20000:]
            try:
                result = subprocess.run(
                    argv, cwd=self.root, capture_output=True, text=True, timeout=remaining, check=False,
                    env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(self.root)},
                )
            except subprocess.TimeoutExpired:
                reports.append(f"{label}: total 180 second game-check limit reached")
                return "exit_code=124\n" + "\n\n".join(reports)[-20000:]
            output = (result.stdout + "\n" + result.stderr).strip()
            reports.append(f"{label}: exit_code={result.returncode}\n{output[-4000:]}")
            if result.returncode:
                return f"exit_code={result.returncode}\n" + "\n\n".join(reports)[-20000:]
        return "exit_code=0\n" + "\n\n".join(reports)[-20000:]
