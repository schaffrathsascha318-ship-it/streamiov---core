"""Manifest, provenance, and package checks for independent StreamioV games."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from zipfile import BadZipFile, ZipFile


GAME_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RELEASE_EVIDENCE = (
    "unit_tests",
    "gameplay_review",
    "accessibility_review",
    "rights_review",
    "release_review",
)


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _safe_repo_file(repository_root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        return None
    posix = PurePosixPath(relative)
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        return None
    root = repository_root.resolve()
    candidate = root.joinpath(*posix.parts)
    current = root
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def audit_game(manifest_path: str | Path, repository_root: str | Path) -> dict:
    manifest_path = Path(os.path.abspath(Path(manifest_path)))
    root = Path(repository_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        manifest_relative = manifest_path.relative_to(root)
    except ValueError:
        return {"valid": False, "release_ready": False, "errors": ["manifest file is outside the repository"], "warnings": []}
    if manifest_path.is_symlink() or any((root / part).is_symlink() for part in _prefixes(manifest_relative)):
        return {"valid": False, "release_ready": False, "errors": ["manifest path contains a symlink"], "warnings": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {"valid": False, "release_ready": False, "errors": [f"manifest unreadable: {type(exc).__name__}"], "warnings": []}
    if not isinstance(manifest, dict):
        return {"valid": False, "release_ready": False, "errors": ["manifest root must be a JSON object"], "warnings": []}

    game_id = manifest.get("id")
    if not isinstance(game_id, str) or not GAME_ID.fullmatch(game_id):
        errors.append("id must be a lowercase hyphenated identifier")
    if manifest.get("schema_version") != 1:
        errors.append("unsupported schema_version")
    if manifest.get("status") not in {"PROTOTYPE", "RELEASED"}:
        errors.append("status must be PROTOTYPE or RELEASED")
    if not isinstance(manifest.get("title"), str) or not manifest["title"].strip():
        errors.append("title is required")
    genres = manifest.get("genre")
    if not isinstance(genres, list) or not genres or any(not isinstance(item, str) or not item.strip() for item in genres):
        errors.append("genre must list one or more named genres")

    project_root = manifest_path.parent.resolve()
    try:
        project_relative = project_root.relative_to(root)
    except ValueError:
        project_relative = None
        errors.append("manifest project directory is outside the repository")
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint or Path(entrypoint).is_absolute() or ".." in Path(entrypoint).parts:
        errors.append("entrypoint must be a safe relative path")
    elif project_relative is None or _safe_repo_file(root, (project_relative / entrypoint).as_posix()) is None:
        errors.append("entrypoint file is missing or is a symlink")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance record is required")
        provenance = {}
    for key in ("concept", "code", "art", "fonts", "audio", "ownership_review"):
        if not isinstance(provenance.get(key), str) or not provenance[key].strip():
            errors.append(f"provenance.{key} is required")
    if not isinstance(provenance.get("external_assets"), list):
        errors.append("provenance.external_assets must be a list")

    package_path = _safe_repo_file(root, manifest.get("package"))
    checksum_path = _safe_repo_file(root, manifest.get("package_checksum"))
    if package_path is None:
        errors.append("package must name an existing repository-relative file without symlink traversal")
    if checksum_path is None:
        errors.append("package_checksum must name an existing repository-relative checksum file")
    elif package_path is not None:
        try:
            checksum_line = checksum_path.read_text(encoding="ascii").strip()
            match = re.fullmatch(r"([0-9a-f]{64})\s+\*?([A-Za-z0-9._-]+)", checksum_line)
            actual = hashlib.sha256(package_path.read_bytes()).hexdigest()
            if not match or match.group(1) != actual or match.group(2) != package_path.name:
                errors.append("package checksum does not match the archive")
        except (OSError, UnicodeError):
            errors.append("package checksum could not be verified")
        if package_path.suffix.lower() == ".zip":
            try:
                with ZipFile(package_path) as archive:
                    bad_member = archive.testzip()
                    if bad_member:
                        errors.append("package contains a corrupt ZIP member")
                    for member in archive.infolist():
                        member_path = PurePosixPath(member.filename)
                        mode = member.external_attr >> 16
                        if (member_path.is_absolute() or ".." in member_path.parts or "\\" in member.filename
                                or any(part.startswith(".") for part in member_path.parts)
                                or (mode & 0o170000) == 0o120000):
                            errors.append("package contains an unsafe path or symlink")
                            break
                    manifest_member = manifest.get("package_manifest")
                    names = archive.namelist()
                    if len(names) != len(set(names)):
                        errors.append("package contains duplicate ZIP paths")
                    if not isinstance(manifest_member, str) or manifest_member not in names:
                        errors.append("package_manifest must identify the manifest stored in the ZIP")
                    else:
                        try:
                            packaged_manifest = json.loads(archive.read(manifest_member), object_pairs_hook=_strict_object)
                            if packaged_manifest != manifest:
                                errors.append("packaged manifest differs from the audited manifest")
                        except (KeyError, RuntimeError, UnicodeError, json.JSONDecodeError, ValueError):
                            errors.append("packaged manifest is invalid")
                    package_files = manifest.get("package_files")
                    if (not isinstance(package_files, list) or not package_files
                            or any(not isinstance(item, str) for item in package_files)
                            or len(package_files) != len(set(package_files))):
                        errors.append("package_files must list unique project-relative source files")
                    elif isinstance(manifest_member, str):
                        if "manifest.json" not in package_files:
                            errors.append("package_files must include manifest.json")
                        if isinstance(entrypoint, str) and entrypoint not in package_files:
                            errors.append("package_files must include the game entrypoint")
                        package_prefix = PurePosixPath(manifest_member).parent
                        expected_members = {manifest_member}
                        for relative_file in package_files:
                            relative_path = PurePosixPath(relative_file)
                            if (relative_path.is_absolute() or ".." in relative_path.parts
                                    or "\\" in relative_file or any(part.startswith(".") for part in relative_path.parts)):
                                errors.append("package_files contains an unsafe source path")
                                continue
                            source = (_safe_repo_file(root, (project_relative / relative_file).as_posix())
                                      if project_relative is not None else None)
                            member_name = (package_prefix / relative_path).as_posix()
                            expected_members.add(member_name)
                            if source is None:
                                errors.append(f"package source is missing or unsafe: {relative_file}")
                            elif member_name not in names:
                                errors.append(f"package is missing source file: {relative_file}")
                            else:
                                try:
                                    if archive.read(member_name) != source.read_bytes():
                                        errors.append(f"packaged source differs from project file: {relative_file}")
                                except (KeyError, OSError, RuntimeError):
                                    errors.append(f"packaged source could not be checked: {relative_file}")
                        actual_files = {name for name in names if not name.endswith("/")}
                        if actual_files != expected_members:
                            errors.append("package contains unexpected or unlisted files")
            except (OSError, BadZipFile):
                errors.append("package is not a readable ZIP archive")

    verification = manifest.get("verification")
    if not isinstance(verification, dict):
        errors.append("verification record is required")
        verification = {}
    status = manifest.get("status")
    release_ready = not errors
    if status == "PROTOTYPE":
        warnings.append("prototype cannot be presented as a released game")
        release_ready = False
    elif status == "RELEASED":
        for key in RELEASE_EVIDENCE:
            if verification.get(key) != "passed":
                errors.append(f"release requires verification.{key} == 'passed'")
                release_ready = False
        if provenance.get("ownership_review") != "verified":
            errors.append("release requires verified provenance ownership_review")
            release_ready = False
        platform_checks = verification.get("platforms")
        if not isinstance(platform_checks, dict) or not any(
            value in {"DEVICE_TESTED", "SUPPORTED"} for value in platform_checks.values()
        ):
            errors.append("release requires at least one device-tested platform in verification.platforms")
            release_ready = False

    return {
        "valid": not errors,
        "release_ready": release_ready and not errors,
        "game_id": game_id if isinstance(game_id, str) else None,
        "status": status if isinstance(status, str) else None,
        "errors": errors,
        "warnings": warnings,
    }


def _prefixes(path: Path):
    parts = path.parts
    return (Path(*parts[:index]) for index in range(1, len(parts) + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to a game's manifest.json")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--require-release", action="store_true", help="Return failure unless release evidence is complete")
    args = parser.parse_args(argv)
    result = audit_game(args.manifest, args.repository_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        return 1
    if args.require_release and not result["release_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
