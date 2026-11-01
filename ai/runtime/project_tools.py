"""Constrained project tools: safe file access and fixed test commands only."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path, PurePosixPath

class ToolError(RuntimeError):
    pass

DENIED_PARTS = {".git", ".env", ".wrangler", "node_modules", "dist", "__pycache__", "secrets", "oauth", ".ssh"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
TEST_COMMANDS = {
    "python -m unittest discover -s tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
}
MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 100

class ProjectTools:
    def __init__(self, root: str | Path, writable_prefixes: tuple[str, ...] = ("ai/", "docs/ai-development/", "tests/")) -> None:
        self.root = Path(root).resolve()
        self.writable_prefixes = writable_prefixes

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
        if not any(normalized.startswith(prefix) for prefix in self.writable_prefixes):
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

    def read_file(self, path: str) -> str:
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
        target.write_text(updated, encoding="utf-8")
        return f"Updated {normalized}: one exact match replaced."

    def run_tests(self, command: str) -> str:
        argv = TEST_COMMANDS.get(command)
        if argv is None:
            raise ToolError("Test command is not allowlisted.")
        result = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=180, check=False, env={"PATH": __import__("os").environ.get("PATH", ""), "PYTHONPATH": str(self.root)})
        output = (result.stdout + "\n" + result.stderr).strip()
        return f"exit_code={result.returncode}\n{output[-12000:]}"
