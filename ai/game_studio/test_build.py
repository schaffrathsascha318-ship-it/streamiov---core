"""Deterministic test-build artifacts for externally commissioned game orders."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from typing import Any
import zipfile

from ai.game_studio.builder import SAFE_ID
from ai.game_studio.orders import (
    OrderIntakeError,
    _read_json,
    _utc_now,
    _workspace,
    update_mission,
)

SCHEMA_VERSION = 1
BUILD_KIND = "test_build"
BUILD_FOLDER = "test_builds"
MANIFEST_NAME = "test-build-manifest.json"
VERIFICATION_NAME = "test-build-verification.json"
DEFAULT_SOURCES = (
    "design-brief.json",
    "builder-audit.json",
    "order.json",
    "access.json",
    "README.md",
)
CLAIM_FLAGS = ("release_ready", "playability_verified", "gameplay_verified", "published")


class TestBuildError(ValueError):
    """Safe-to-return validation or artifact error."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _safe_build_dir(repository_root: str | Path, order_id: Any, build_id: Any) -> tuple[Path, Path]:
    workspace = _workspace(repository_root, order_id)
    if not isinstance(build_id, str) or not SAFE_ID.fullmatch(build_id) or len(build_id) > 60:
        raise TestBuildError("Ungültige Build-ID.")
    build_dir = workspace / BUILD_FOLDER / build_id
    if build_dir.is_symlink():
        raise TestBuildError("Build-Verzeichnis darf kein Symlink sein.")
    if build_dir.exists() and not build_dir.is_dir():
        raise TestBuildError("Build-Pfad ist kein Verzeichnis.")
    return workspace, build_dir


def _source_bytes(workspace: Path, include_paths: Any) -> dict[str, bytes]:
    paths = list(DEFAULT_SOURCES)
    if include_paths is not None:
        if not isinstance(include_paths, (list, tuple)):
            raise TestBuildError("include_paths muss eine Liste sein.")
        paths.extend(include_paths)
    collected: dict[str, bytes] = {}
    root = workspace.resolve()
    for raw in paths:
        if not isinstance(raw, str) or not raw or raw.startswith("/") or "\\" in raw:
            raise TestBuildError("Ungültiger Quellpfad.")
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
            raise TestBuildError("Ungültiger Quellpfad.")
        path = workspace.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise TestBuildError("Quellpfad verlässt den Auftragsarbeitsbereich.")
        name = relative.as_posix()
        if name in collected:
            continue
        collected[name] = path.read_bytes()
    if not collected:
        raise TestBuildError("Keine Quelldateien für den Test-Build gefunden.")
    return collected


def _write_zip(path: Path, prefix: str, sources: dict[str, bytes]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".test-build-", dir=str(path.parent))
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(sources):
                info = zipfile.ZipInfo(f"{prefix}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, sources[name])
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_order_test_build(
    repository_root: str | Path,
    order_id: Any,
    *,
    build_id: str | None = None,
    actor: str = "ai-chief",
    include_paths: list[str] | tuple[str, ...] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    workspace, build_dir = _safe_build_dir(
        repository_root, order_id, build_id or datetime.now(timezone.utc).strftime("tb-%Y%m%dt%H%M%Sz")
    )
    build_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    sources = _source_bytes(workspace, include_paths)
    package_name = f"{order_id}-{build_dir.name}-test-build.zip"
    sidecar_name = package_name + ".sha256"
    package = build_dir / package_name
    sidecar = build_dir / sidecar_name
    manifest_path = build_dir / MANIFEST_NAME
    if not force and any(path.exists() for path in (package, sidecar, manifest_path)):
        raise TestBuildError("Für diese Build-ID existiert bereits ein Test-Build; force=True erforderlich.")
    _write_zip(package, f"{order_id}-{build_dir.name}", sources)
    package_bytes = package.read_bytes()
    digest = _sha256(package_bytes)
    sidecar.write_text(digest + "  " + package_name + "\n", encoding="utf-8")
    os.chmod(sidecar, 0o600)
    publication = _read_json(workspace / "publication.json")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "build_kind": BUILD_KIND,
        "order_id": order_id,
        "build_id": build_dir.name,
        "workspace": _relative(workspace, root),
        "created_at": _utc_now(),
        "builder": " ".join(str(actor or "ai-chief").split())[:80],
        "status": "TEST_BUILD_CREATED",
        "release_ready": False,
        "playability_verified": False,
        "gameplay_verified": False,
        "published": False,
        "publication_authorized": publication.get("approved") is True,
        "package": package_name,
        "package_checksum": sidecar_name,
        "package_sha256": digest,
        "package_bytes": len(package_bytes),
        "files": [
            {"path": name, "sha256": _sha256(data), "bytes": len(data)}
            for name, data in sorted(sources.items())
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    evidence = _relative(manifest_path, root)
    update_mission(repository_root, order_id, "build", "in_progress", evidence_ref=evidence, actor=actor)
    return {
        "ok": True,
        "status": "TEST_BUILD_CREATED",
        "order_id": order_id,
        "build_id": build_dir.name,
        "workspace": manifest["workspace"],
        "manifest": evidence,
        "package": _relative(package, root),
        "package_sha256": digest,
        "files": len(sources),
    }


def _validate_claims(manifest: dict[str, Any]) -> list[str]:
    errors = []
    if manifest.get("build_kind") != BUILD_KIND:
        errors.append("build_kind ist nicht test_build.")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("manifest_schema_unsupported")
    for flag in CLAIM_FLAGS:
        if manifest.get(flag) is not False:
            errors.append(f"unzulässige Behauptung: {flag}")
    return errors


def _verify_archive(package: Path, manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    checks = ["sidecar_sha256", "zip_integrity", "zip_members_match_manifest", "file_hashes_match"]
    errors = []
    sibling = package.parent / str(manifest.get("package_checksum", ""))
    if sibling.name != str(manifest.get("package_checksum")) or not sibling.is_file() or sibling.is_symlink():
        return checks, ["checksum_sidecar_missing"]
    expected_digest = str(manifest.get("package_sha256", ""))
    line = sibling.read_text(encoding="utf-8")
    if line != f"{expected_digest}  {package.name}\n":
        return checks, ["checksum_sidecar_mismatch"]
    actual_digest = _sha256(package.read_bytes())
    if actual_digest != expected_digest:
        return checks, ["package_sha256_mismatch"]
    try:
        with zipfile.ZipFile(package) as archive:
            if archive.testzip() is not None:
                return checks, ["zip_integrity_failed"]
            entries = manifest.get("files")
            if not isinstance(entries, list) or not entries:
                return checks, ["manifest_files_missing"]
            expected_names = {f"{manifest['order_id']}-{manifest['build_id']}/{item['path']}" for item in entries}
            actual_names = archive.namelist()
            if len(actual_names) != len(set(actual_names)):
                return checks, ["duplicate_zip_members"]
            if set(actual_names) != expected_names:
                return checks, ["zip_members_mismatch"]
            for item in entries:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    return checks, ["manifest_entry_invalid"]
                relative = PurePosixPath(item["path"])
                if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
                    return checks, ["unsafe_manifest_path"]
                data = archive.read(f"{manifest['order_id']}-{manifest['build_id']}/{item['path']}")
                if _sha256(data) != item.get("sha256") or len(data) != item.get("bytes"):
                    return checks, ["file_hash_mismatch"]
    except (OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        return checks, [f"archive_error:{type(exc).__name__}"]
    return checks, errors


def verify_order_test_build(
    repository_root: str | Path,
    order_id: Any,
    *,
    build_id: str | None = None,
    actor: str = "ai-chief",
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    workspace, build_dir = _safe_build_dir(repository_root, order_id, build_id)
    manifest_path = build_dir / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise TestBuildError("Test-Build-Manifest fehlt.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TestBuildError("Test-Build-Manifest ist ungültig.") from exc
    if not isinstance(manifest, dict):
        raise TestBuildError("Test-Build-Manifest ist ungültig.")
    checks = ["manifest_schema", "safe_paths", "non_release_claims"]
    errors = _validate_claims(manifest)
    package_name = manifest.get("package")
    if not isinstance(package_name, str) or PurePosixPath(package_name).name != package_name:
        errors.append("unsafe_package_path")
        package = None
    else:
        package = build_dir / package_name
        if package.is_symlink() or not package.is_file():
            errors.append("package_missing")
            package = None
    if package is not None:
        archive_checks, archive_errors = _verify_archive(package, manifest)
        checks.extend(archive_checks)
        errors.extend(archive_errors)
    if not errors:
        entries = manifest.get("files")
        names = []
        if not isinstance(entries, list) or not entries:
            errors.append("manifest_files_missing")
        else:
            for item in entries:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    errors.append("manifest_entry_invalid")
                    break
                names.append(item["path"])
        if not errors:
            try:
                sources = _source_bytes(workspace, names)
            except TestBuildError as exc:
                errors.append(str(exc))
            checks.append("source_snapshot_matches_workspace")
            if any(_sha256(sources.get(item["path"], b"")) != item["sha256"] for item in entries):
                errors.append("source_drift")
    verdict = {
        "ok": not errors,
        "status": "TEST_BUILD_VERIFIED" if not errors else "TEST_BUILD_VERIFICATION_FAILED",
        "order_id": order_id,
        "build_id": build_dir.name,
        "checks": checks,
        "errors": errors,
        "warnings": [],
        "verified_at": _utc_now(),
        "verifier": " ".join(str(actor or "ai-chief").split())[:80],
        "claim_boundary": {
            "test_build": True,
            "playability_verified": False,
            "release_ready": False,
            "published": False,
        },
    }
    report_path = build_dir / VERIFICATION_NAME
    report_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    os.chmod(report_path, 0o600)
    evidence = _relative(report_path, root)
    verdict["report"] = evidence
    mission_status = "verified" if verdict["ok"] else "blocked"
    update_mission(repository_root, order_id, "build", mission_status, evidence_ref=evidence, actor=actor)
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and verify a non-release test build for an external game order.")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--order-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true", help="Create a deterministic test-build artifact.")
    mode.add_argument("--verify", action="store_true", help="Verify an existing test-build artifact.")
    parser.add_argument("--build-id")
    parser.add_argument("--actor", default="ai-chief")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.build:
            result = build_order_test_build(
                args.repository_root, args.order_id, build_id=args.build_id,
                actor=args.actor, force=args.force,
            )
        else:
            result = verify_order_test_build(
                args.repository_root, args.order_id, build_id=args.build_id, actor=args.actor,
            )
    except (TestBuildError, OrderIntakeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
