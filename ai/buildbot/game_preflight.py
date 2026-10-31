"""Fail-closed static preflight for Streamiov game packages.

Static checks never claim that a game is playable: browser execution must be
verified separately before a package can be released.
"""
from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


MAX_MANIFEST_BYTES = 128_000
MAX_ENTRY_BYTES = 2_000_000


class _ResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.resources: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.resources.append(("script", values["src"] or ""))
        elif tag in {"iframe", "frame"} and values.get("src"):
            self.resources.append(("frame", values["src"] or ""))
        elif tag == "object" and values.get("data"):
            self.resources.append(("object", values["data"] or ""))


def _safe_local_file(root: Path, raw: str) -> Path | None:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc or raw.startswith(("/", "#")):
        return None
    path = PurePosixPath(parsed.path)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    candidate = root.joinpath(*path.parts)
    if candidate.is_symlink():
        return None
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        return None
    return candidate


def validate_game_package(game_dir: str | Path) -> dict:
    """Return static package checks; never infer browser playability or release readiness."""
    root = Path(game_dir).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = root / "streamiov-game.json"
    entry_path: Path | None = None

    if not root.is_dir():
        errors.append("game_directory_missing")
    elif not manifest_path.is_file() or manifest_path.is_symlink():
        errors.append("manifest_missing")
    elif manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        errors.append("manifest_too_large")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            manifest = None
            errors.append("manifest_invalid_json")
        if manifest is not None:
            if not isinstance(manifest, dict):
                errors.append("manifest_must_be_object")
            else:
                entry = manifest.get("entry") or manifest.get("entrypoint") or manifest.get("main") or "index.html"
                entry_path = _safe_local_file(root, entry)
                if entry_path is None:
                    errors.append("entry_path_unsafe")
                elif not entry_path.is_file():
                    errors.append("entry_file_missing")
                elif entry_path.stat().st_size > MAX_ENTRY_BYTES:
                    errors.append("entry_file_too_large")
                elif entry_path.suffix.lower() not in {".html", ".htm"}:
                    errors.append("entry_must_be_html")

    checked_resources = 0
    external_resources: list[dict[str, str]] = []
    missing_resources: list[str] = []
    if entry_path is not None and entry_path.is_file() and entry_path.stat().st_size <= MAX_ENTRY_BYTES:
        try:
            html = entry_path.read_text(encoding="utf-8")
            if "</html>" not in html.lower():
                errors.append("entry_html_incomplete")
            parser = _ResourceParser()
            parser.feed(html)
            parser.close()
            for kind, raw in parser.resources:
                checked_resources += 1
                local = _safe_local_file(root, raw)
                if local is None:
                    external_resources.append({"type": kind, "source": raw[:500]})
                elif not local.is_file():
                    missing_resources.append(raw)
        except (OSError, UnicodeError, ValueError):
            errors.append("entry_html_unreadable")

    if external_resources:
        warnings.append("external_runtime_resources_detected")
    if missing_resources:
        errors.append("local_runtime_resource_missing")

    static_valid = not errors
    return {
        "static_valid": static_valid,
        "errors": errors,
        "warnings": warnings,
        "missing_resources": missing_resources,
        "external_resources": external_resources,
        "checked_local_resource_references": checked_resources,
        "entry": entry_path.relative_to(root).as_posix() if entry_path is not None and entry_path.exists() else None,
        "browser_playability_verified": False,
        "download_ready": False,
        "production_deployed": False,
        "release_status": "NOT_RELEASED",
    }
