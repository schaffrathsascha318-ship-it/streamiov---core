"""Constrained project tools: safe file access and fixed test commands only."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

class ToolError(RuntimeError):
    pass

DENIED_PARTS = {".git", ".env", ".wrangler", "node_modules", "__pycache__", "secrets", "oauth", ".ssh"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
TEST_COMMANDS = {
    "python -m unittest discover -s tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
}
MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 100

class ProjectTools:
    def __init__(self, root: str | Path, writable_prefixes: tuple[str, ...] = ("ai/", "docs/ai-development/", "tests/"), *, allow_game_checks: bool = False) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ToolError("Project workspace root must be an existing directory.")
        if not isinstance(writable_prefixes, (tuple, list)) or not writable_prefixes:
            raise ToolError("At least one explicit writable directory scope is required.")
        normalized = []
        for prefix in writable_prefixes:
            if not isinstance(prefix, str) or not prefix or "\\" in prefix or "\x00" in prefix:
                raise ToolError("Writable scopes must be normalized relative directory paths.")
            candidate = PurePosixPath(prefix)
            if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
                raise ToolError("Writable scopes may not be absolute or contain path traversal.")
            if any(part.lower() in DENIED_PARTS or part.lower().startswith(".env") for part in candidate.parts):
                raise ToolError("Writable scopes may not include protected directories.")
            value = candidate.as_posix().rstrip("/") + "/"
            if value == "/" or value in normalized:
                raise ToolError("Writable scopes must be unique project subdirectories.")
            normalized.append(value)
        self.writable_prefixes = tuple(normalized)
        self.allow_game_checks = allow_game_checks

    def _resolve(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ToolError("A valid relative project path is required.")
        rel = PurePosixPath(raw)
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise ToolError("Path must be a normalized relative path without traversal.")
        if any(part.lower() in DENIED_PARTS or part.lower().startswith(".env") or any(word in part.lower() for word in ("secret", "credential", "access-token", "refresh-token")) for part in rel.parts) or rel.suffix.lower() in DENIED_SUFFIXES:
            raise ToolError("Access to protected paths and secret-like files is denied.")

        # Reject symlinks in every existing path component, not only the leaf.
        # A symlinked parent could otherwise redirect reads or writes outside
        # the workspace even when the final target itself is not a symlink.
        candidate = self.root
        for part in rel.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise ToolError("Symlink access is denied.")

        anchor = candidate if candidate.exists() else candidate.parent
        resolved_anchor = anchor.resolve()
        if self.root != resolved_anchor and self.root not in resolved_anchor.parents:
            raise ToolError("Path escapes the project workspace.")
        return candidate

    def _writable_target(self, raw: str) -> tuple[Path, str]:
        target = self._resolve(raw)
        normalized = target.relative_to(self.root).as_posix()
        if not any(normalized.startswith(prefix) for prefix in self.writable_prefixes):
            raise ToolError("Writes are restricted to configured AI, documentation, and test directories.")
        return target, normalized

    def _path_parts(self, raw: str) -> tuple[str, ...]:
        if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
            raise ToolError("A normalized relative project path is required.")
        if raw == ".":
            return ()
        parts = raw.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ToolError("Path must not contain empty, dot, or traversal components.")
        rel = PurePosixPath(raw)
        if rel.is_absolute():
            raise ToolError("Absolute paths are not allowed.")
        if any(
            part.lower() in DENIED_PARTS
            or part.lower().startswith(".env")
            or any(word in part.lower() for word in ("secret", "credential", "access-token", "refresh-token"))
            for part in parts
        ) or rel.suffix.lower() in DENIED_SUFFIXES:
            raise ToolError("Access to protected paths and secret-like files is denied.")
        return tuple(parts)

    def _require_dirfd_support(self) -> None:
        if (
            os.name != "posix"
            or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")
            or os.open not in os.supports_dir_fd
            or os.mkdir not in os.supports_dir_fd
        ):
            raise ToolError("Race-safe workspace access requires POSIX openat/O_NOFOLLOW support.")

    def _open_directory(self, parts: tuple[str, ...], *, create: bool = False) -> int:
        self._require_dirfd_support()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.root, flags)
        try:
            for part in parts:
                try:
                    next_fd = os.open(part, flags, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, mode=0o755, dir_fd=fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _read_fd(fd: int, limit: int) -> bytes:
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ToolError("File exceeds the configured read limit.")
        return b"".join(chunks)

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ToolError("File write did not make progress.")
            view = view[written:]

    def list_files(self, path: str = ".") -> str:
        """List bounded, non-symlink children using a pinned directory."""
        import stat
        parts = self._path_parts(path)
        fd = self._open_directory(parts)
        try:
            entries = []
            for name in sorted(os.listdir(fd), key=str.lower):
                lowered = name.lower()
                if (
                    lowered in DENIED_PARTS
                    or lowered.startswith(".env")
                    or any(word in lowered for word in ("secret", "credential", "access-token", "refresh-token"))
                    or Path(name).suffix.lower() in DENIED_SUFFIXES
                ):
                    continue
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(info.st_mode):
                    continue
                kind = "dir" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
                if kind == "other":
                    continue
                entries.append(f"{kind} {name}")
                if len(entries) >= MAX_LIST_ENTRIES:
                    break
            suffix = "\n[listing capped at 100 entries]" if len(entries) >= MAX_LIST_ENTRIES else ""
            return "\n".join(entries) + suffix if entries else "(directory is empty or contains only excluded entries)"
        finally:
            os.close(fd)

    def read_file(self, path: str) -> str:
        import stat
        parts = self._path_parts(path)
        if not parts:
            raise ToolError("A file path is required.")
        parent_fd = self._open_directory(parts[:-1])
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ToolError("Requested path is not a regular file.")
                return self._read_fd(fd, MAX_FILE_BYTES).decode("utf-8")
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

    def write_file(self, path: str, content: str) -> str:
        parts = self._path_parts(path)
        if not parts:
            raise ToolError("A file path is required.")
        normalized = "/".join(parts)
        if not any(normalized.startswith(prefix) for prefix in self.writable_prefixes):
            raise ToolError("Writes are restricted to configured AI, documentation, and test directories.")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 100_000:
            raise ToolError("Content must be text no larger than 100 KB.")
        parent_fd = self._open_directory(parts[:-1], create=True)
        try:
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent_fd)
            try:
                self._write_all(fd, content.encode("utf-8"))
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)
        return f"Created {normalized} ({len(content)} characters)."

    def replace_text(self, path: str, old_text: str, new_text: str) -> str:
        """Replace one exact, unique range through a pinned file descriptor."""
        import stat
        parts = self._path_parts(path)
        if not parts:
            raise ToolError("A file path is required.")
        normalized = "/".join(parts)
        if not any(normalized.startswith(prefix) for prefix in self.writable_prefixes):
            raise ToolError("Writes are restricted to configured AI, documentation, and test directories.")
        if not isinstance(old_text, str) or not old_text:
            raise ToolError("old_text must be a non-empty string.")
        if not isinstance(new_text, str) or old_text == new_text:
            raise ToolError("new_text must be text different from old_text.")
        parent_fd = self._open_directory(parts[:-1])
        try:
            fd = os.open(parts[-1], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ToolError("Exact-match edits require an existing regular file.")
                original = self._read_fd(fd, MAX_FILE_BYTES).decode("utf-8")
                matches = original.count(old_text)
                if matches != 1:
                    raise ToolError(f"Exact-match edit requires one occurrence; found {matches}. No change made.")
                updated = original.replace(old_text, new_text, 1).encode("utf-8")
                if len(updated) > MAX_FILE_BYTES:
                    raise ToolError("Edited file would exceed the 200 KB limit.")
                os.lseek(fd, 0, os.SEEK_SET)
                os.ftruncate(fd, 0)
                self._write_all(fd, updated)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)
        return f"Updated {normalized}: one exact match replaced."

    def run_tests(self, command: str) -> str:
        argv = TEST_COMMANDS.get(command)
        if argv is None:
            raise ToolError("Test command is not allowlisted.")
        result = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=180, check=False, env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(self.root)})
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
