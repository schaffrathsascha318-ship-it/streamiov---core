"""Constrained project tools: safe file access and fixed test commands only."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
import hashlib
import tempfile
import uuid
import stat
from pathlib import Path, PurePosixPath
from .sandbox import run_sandboxed

class ToolError(RuntimeError):
    pass

DENIED_PARTS = {".git", ".env", ".wrangler", ".streamiov-recovery", "node_modules", "__pycache__", "secrets", "oauth", ".ssh"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
TEST_COMMANDS = {
    "python -m unittest discover -s tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
}
MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 100
MAX_READ_CHARS = 10_000

class ProjectTools:
    def __init__(self, root: str | Path, writable_prefixes: tuple[str, ...] = ("ai/", "docs/ai-development/", "tests/"), *, allow_game_checks: bool = False) -> None:
        self.root = Path(root).resolve()
        self.writable_prefixes = writable_prefixes
        self.allow_game_checks = allow_game_checks

    def _resolve(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ToolError("A valid relative project path is required.")
        rel = PurePosixPath(raw)
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise ToolError("Path must be a normalized relative path without traversal.")
        if any(part.lower() in DENIED_PARTS or part.lower().startswith(".env") or any(word in part.lower() for word in ("secret", "credential", "access-token", "refresh-token")) for part in rel.parts) or rel.suffix.lower() in DENIED_SUFFIXES:
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
        target = self._resolve(raw)
        normalized = target.relative_to(self.root).as_posix()
        if "**" not in self.writable_prefixes and not any(normalized.startswith(prefix) for prefix in self.writable_prefixes):
            raise ToolError("Writes are restricted to configured AI, documentation, and test directories.")
        return target, normalized

    def list_files(self, path: str = ".") -> str:
        """List a bounded set of safe immediate children inside the project workspace."""
        target = self.root if path == "." else self._resolve(path)
        if not target.is_dir():
            raise ToolError("Requested path is not a project directory.")
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            lowered = child.name.lower()
            if child.is_symlink():
                continue
            if lowered in DENIED_PARTS or lowered.startswith(".env"):
                continue
            if any(word in lowered for word in ("secret", "credential", "access-token", "refresh-token")):
                continue
            if child.suffix.lower() in DENIED_SUFFIXES:
                continue
            kind = "dir" if child.is_dir() else "file" if child.is_file() else "other"
            if kind == "other":
                continue
            entries.append(f"{kind} {child.name}")
            if len(entries) >= MAX_LIST_ENTRIES:
                break
        suffix = "\n[listing capped at 100 entries]" if len(entries) >= MAX_LIST_ENTRIES else ""
        return "\n".join(entries) + suffix if entries else "(directory is empty or contains only excluded entries)"

    def read_file(
        self,
        path: str,
        start_line: str | None = None,
        end_line: str | None = None,
    ) -> str:
        """Read a complete small file or a bounded, numbered section of a larger file."""
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError("Requested file does not exist or is not a regular file.")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ToolError("File exceeds the 200 KB read limit.")

        def parse_line(value: str | None, label: str) -> int | None:
            if value is None:
                return None
            if not isinstance(value, str) or not value.isdigit() or int(value) < 1:
                raise ToolError(f"{label} must be a positive line number.")
            return int(value)

        start = parse_line(start_line, "start_line")
        end = parse_line(end_line, "end_line")
        if start is not None and end is not None and end < start:
            raise ToolError("end_line must be greater than or equal to start_line.")

        content = target.read_text(encoding="utf-8")
        if start is None and end is None and len(content) <= MAX_READ_CHARS:
            return content

        lines = content.splitlines(keepends=True)
        total = len(lines)
        if total == 0:
            return content

        first = start or 1
        last = min(end or total, total)
        if first > total:
            raise ToolError(f"start_line exceeds the file length ({total} lines).")

        chunks = []
        used = 0
        included_last = first - 1
        next_line = None

        for number in range(first, last + 1):
            line = lines[number - 1]
            remaining = MAX_READ_CHARS - used
            if len(line) > remaining:
                if remaining > 0:
                    chunks.append(line[:remaining])
                    used += remaining
                next_line = number
                break
            chunks.append(line)
            used += len(line)
            included_last = number

        if next_line is None and included_last < last:
            next_line = included_last + 1
        if next_line is None and last < total:
            next_line = last + 1

        header = f"[File: {path} | lines {first}-{max(included_last, first)} of {total}]"
        if next_line is not None:
            header += f"\n[Continue reading at line {next_line}]"
        return header + "\n" + "".join(chunks)

    def file_info(self, path: str) -> str:
        """Return safe metadata needed for optimistic-concurrency edits."""
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError("Requested file does not exist or is not a regular file.")
        data = target.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise ToolError("File exceeds the 200 KB metadata limit.")
        digest = hashlib.sha256(data).hexdigest()
        return f"File: {path}\\nBytes: {len(data)}\\nSHA-256: {digest}"

    def edit_file(self, path: str, expected_sha256: str, content: str) -> str:
        """Safely replace a complete file after hash verification and backup."""
        target, normalized = self._writable_target(path)
        if not target.is_file():
            raise ToolError("Full-file edits require an existing regular file.")
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256.lower())
        ):
            raise ToolError("expected_sha256 must be a 64-character SHA-256 hex digest.")
        if not isinstance(content, str):
            raise ToolError("New file content must be text.")
        updated = content.encode("utf-8")
        if len(updated) > MAX_FILE_BYTES:
            raise ToolError("Edited file would exceed the 200 KB limit.")

        original = target.read_bytes()
        if len(original) > MAX_FILE_BYTES:
            raise ToolError("File exceeds the 200 KB edit limit.")
        old_hash = hashlib.sha256(original).hexdigest()
        if old_hash != expected_sha256.lower():
            raise ToolError("File changed since inspection; hash mismatch. Read it again before editing.")

        recovery_root = self.root / ".streamiov-recovery"
        if recovery_root.is_symlink():
            raise ToolError("Recovery directory must not be a symlink.")
        backup_root = recovery_root / "backups"
        if backup_root.is_symlink():
            raise ToolError("Backup directory must not be a symlink.")
        backup_root.mkdir(parents=True, exist_ok=True)
        resolved_backup_root = backup_root.resolve()
        if self.root != resolved_backup_root and self.root not in resolved_backup_root.parents:
            raise ToolError("Backup directory escapes the project workspace.")

        backup_name = f"{time.time_ns()}-{uuid.uuid4().hex}-{target.name}.bak"
        backup_path = backup_root / backup_name
        with backup_path.open("xb") as backup:
            backup.write(original)
            backup.flush()
            os.fsync(backup.fileno())

        temp_path = None
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
            fd, temp_name = tempfile.mkstemp(prefix=".streamiov-edit-", dir=target.parent)
            temp_path = Path(temp_name)
            with os.fdopen(fd, "wb") as temporary:
                temporary.write(updated)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temp_path, mode)

            # Recheck immediately before replacement to detect concurrent edits.
            current = target.read_bytes()
            if hashlib.sha256(current).hexdigest() != old_hash:
                raise ToolError("File changed during editing; no replacement was made.")

            os.replace(temp_path, target)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass

        new_hash = hashlib.sha256(updated).hexdigest()
        backup_relative = backup_path.relative_to(self.root).as_posix()
        return (
            f"Updated {normalized}.\\n"
            f"Old SHA-256: {old_hash}\\n"
            f"New SHA-256: {new_hash}\\n"
            f"Backup: {backup_relative}"
        )

    def write_file(self, path: str, content: str) -> str:
        target, normalized = self._writable_target(path)
        if not isinstance(content, str) or len(content.encode("utf-8")) > 100_000:
            raise ToolError("Content must be text no larger than 100 KB.")
        if target.exists():
            raise ToolError("Refusing to overwrite an existing file; use an exact-match edit or submit a focused patch through review.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Created {normalized} ({len(content)} characters)."

    def replace_text(self, path: str, old_text: str, new_text: str) -> str:
        """Replace one exact, unique text range in an allowed existing file."""
        target, normalized = self._writable_target(path)
        if not target.is_file():
            raise ToolError("Exact-match edits require an existing regular file.")
        if not isinstance(old_text, str) or not old_text:
            raise ToolError("old_text must be a non-empty string.")
        if not isinstance(new_text, str) or old_text == new_text:
            raise ToolError("new_text must be text different from old_text.")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ToolError("File exceeds the 200 KB edit limit.")
        original = target.read_text(encoding="utf-8")
        matches = original.count(old_text)
        if matches != 1:
            raise ToolError(f"Exact-match edit requires one occurrence; found {matches}. No change made.")
        updated = original.replace(old_text, new_text, 1)
        if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
            raise ToolError("Edited file would exceed the 200 KB limit.")
        digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
        result = self.edit_file(path, digest, updated)
        return f"one exact match replaced.\n{result}"

    def run_tests(self, command: str) -> str:
        argv = TEST_COMMANDS.get(command)
        if argv is None:
            raise ToolError("Test command is not allowlisted.")
        try:
            result = run_sandboxed(self.root, argv, timeout=180)
        except (OSError, RuntimeError) as exc:
            raise ToolError(str(exc)) from exc
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
            commands.append((["node", "--test", *sorted(node_tests)], "Node game tests"))

        reports = []
        deadline = time.monotonic() + 180
        for argv, label in commands:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reports.append(f"{label}: total 180 second game-check limit reached")
                return "exit_code=124\n" + "\n\n".join(reports)[-20000:]
            try:
                result = run_sandboxed(self.root, argv, timeout=remaining)
            except (OSError, RuntimeError) as exc:
                raise ToolError(f"{label}: sandbox refused execution: {exc}") from exc
            output = (result.stdout + "\n" + result.stderr).strip()
            reports.append(f"{label}: exit_code={result.returncode}\n{output[-4000:]}")
            if result.returncode:
                return f"exit_code={result.returncode}\n" + "\n\n".join(reports)[-20000:]
        return "exit_code=0\n" + "\n\n".join(reports)[-20000:]
