"""Build a deterministic, dependency-free ZIP from a game's manifest file list."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _repo_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Manifest paths must be repository-relative POSIX paths.")
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(part in {".", ".."} or part.startswith(".") for part in parts):
        raise ValueError("Manifest paths must not contain traversal or hidden components.")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Manifest paths may not traverse symlinks.")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("Manifest path is missing or outside the repository.") from exc
    return resolved


def _output_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Package output paths must be repository-relative POSIX paths.")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or any(part in {".", ".."} or part.startswith(".") for part in posix.parts):
        raise ValueError("Package output path must not contain traversal or hidden components.")
    destination = root.joinpath(*posix.parts)
    current = root
    for part in posix.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("Package output path may not traverse symlinks.")
    if destination.is_symlink():
        raise ValueError("Package output may not be a symlink.")
    try:
        destination.absolute().relative_to(root)
    except ValueError as exc:
        raise ValueError("Package output is outside the repository.") from exc
    return destination


def build_package(manifest_path: str | Path, repository_root: str | Path, *, force: bool = False) -> dict:
    root = Path(repository_root).resolve()
    manifest_file = Path(os.path.abspath(Path(manifest_path)))
    try:
        manifest_relative = manifest_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Manifest must be inside the repository.") from exc
    manifest_file = _repo_path(root, manifest_relative)
    if not manifest_file.is_file():
        raise ValueError("Manifest must be a regular repository file.")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    if not isinstance(manifest, dict):
        raise ValueError("Manifest root must be an object.")
    game_id = manifest.get("id")
    if not isinstance(game_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", game_id):
        raise ValueError("Manifest id is invalid.")
    listed = manifest.get("package_files")
    if not isinstance(listed, list) or not listed or any(not isinstance(name, str) for name in listed):
        raise ValueError("Manifest package_files must be a non-empty list of project-relative files.")
    if len(listed) != len(set(listed)):
        raise ValueError("Manifest package_files contains duplicates.")
    if "manifest.json" not in listed:
        raise ValueError("package_files must include manifest.json.")
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str) or entrypoint not in listed:
        raise ValueError("package_files must include the declared entrypoint.")
    embedded_manifest = manifest.get("package_manifest")
    prefix = PurePosixPath(embedded_manifest).parent if isinstance(embedded_manifest, str) else None
    if prefix is None or prefix.is_absolute() or ".." in prefix.parts or prefix in {PurePosixPath("."), PurePosixPath("")}:
        raise ValueError("package_manifest must include a safe archive directory and filename.")
    if PurePosixPath(embedded_manifest).name != "manifest.json":
        raise ValueError("package_manifest must end in manifest.json.")

    project = manifest_file.parent.resolve()
    members: list[tuple[str, bytes]] = []
    for relative in listed:
        path_parts = PurePosixPath(relative).parts
        if not path_parts or PurePosixPath(relative).is_absolute() or ".." in path_parts:
            raise ValueError("package_files must contain safe project-relative paths.")
        source = _repo_path(root, (project.relative_to(root) / relative).as_posix())
        member = (prefix / PurePosixPath(relative)).as_posix()
        members.append((member, source.read_bytes()))
    if len({name for name, _ in members}) != len(members):
        raise ValueError("Manifest package_files maps to duplicate archive paths.")
    if (prefix / "manifest.json").as_posix() != embedded_manifest:
        raise ValueError("package_manifest must identify the manifest's packaged path.")

    package_relative = manifest.get("package")
    if not isinstance(package_relative, str) or not package_relative.lower().endswith(".zip"):
        raise ValueError("Manifest package must point to a ZIP path.")
    output = _output_path(root, package_relative)
    if output.exists() and not output.is_file():
        raise ValueError("Package output path must be a file.")
    checksum_relative = manifest.get("package_checksum")
    if (not isinstance(checksum_relative, str)
            or PurePosixPath(checksum_relative).parent != PurePosixPath(package_relative).parent
            or PurePosixPath(checksum_relative).name != PurePosixPath(package_relative).name + ".sha256"):
        raise ValueError("Package checksum must be beside the package ZIP.")
    checksum_output = _output_path(root, checksum_relative)
    if checksum_output.exists() and not checksum_output.is_file():
        raise ValueError("Package checksum path must be a file.")

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(members):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.file_size = len(content)
            archive.writestr(info, content, compress_type=ZIP_DEFLATED, compresslevel=9)
    package_bytes = buffer.getvalue()
    digest = hashlib.sha256(package_bytes).hexdigest()
    sidecar = f"{digest}  {output.name}\n".encode("ascii")
    if output.exists() and output.read_bytes() != package_bytes and not force:
        raise FileExistsError("Package differs from existing file. Bump the version or pass --force for a local rebuild.")
    output.parent.mkdir(parents=True, exist_ok=True)
    checksum_output.parent.mkdir(parents=True, exist_ok=True)
    for destination, content in ((output, package_bytes), (checksum_output, sidecar)):
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temp_path, destination)
    return {"game_id": game_id, "package": str(output.relative_to(root)), "sha256": digest, "bytes": len(package_bytes)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Game manifest.json")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--force", action="store_true", help="Replace an existing different local artifact")
    args = parser.parse_args(argv)
    try:
        result = build_package(args.manifest, args.repository_root, force=args.force)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
