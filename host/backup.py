"""Encrypted, consistent and restore-staged backups for the Streamiov host.

Backups use SQLite's online backup API and age public-key encryption. Restore
never overwrites active databases: it only creates a verified staging directory.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid


REQUIRED_DATABASES = ("accounts.sqlite3", "forum.sqlite3", "streamiov-data.sqlite3")
OPTIONAL_DATABASES = ("voice-rooms.sqlite3",)
ALLOWED_DATABASES = frozenset((*REQUIRED_DATABASES, *OPTIONAL_DATABASES))
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DATABASE_BYTES = 20 * 1024 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
BACKUP_PATTERN = re.compile(r"^streamiov-host-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\.tar\.gz\.age$")


class BackupError(RuntimeError):
    """Safe-to-report backup, encryption or restore error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("x", encoding="utf-8") as handle:
            os.chmod(temp, 0o600)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _check_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if not path.is_dir() or path.is_symlink():
        raise BackupError("Backup directory must be a real directory, not a symlink.")
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _check_paths(data_dir: Path, backup_dir: Path) -> None:
    if data_dir == backup_dir:
        raise BackupError("Backup directory must be separate from the live data directory.")
    try:
        common = Path(os.path.commonpath((str(data_dir), str(backup_dir))))
    except ValueError:
        return
    if common == data_dir or common == backup_dir:
        raise BackupError("Backup and live data directories must not contain one another.")


def _age_binary() -> str:
    return os.environ.get("STREAMIOV_AGE_BINARY", "age")


def _age_recipient() -> str:
    recipient = os.environ.get("STREAMIOV_BACKUP_AGE_RECIPIENT", "").strip()
    if not recipient.startswith("age1") or len(recipient) < 30:
        raise BackupError("STREAMIOV_BACKUP_AGE_RECIPIENT must contain the owner's age public recipient.")
    return recipient


def _identity_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("STREAMIOV_BACKUP_AGE_IDENTITY", "")
    if not raw:
        raise BackupError("Restore verification requires the owner's age identity file.")
    path = Path(raw).expanduser()
    try:
        info = path.lstat()
    except OSError as exc:
        raise BackupError("Age identity file is unavailable.") from exc
    if path.is_symlink() or not path.is_file():
        raise BackupError("Age identity must be a regular file, not a symlink.")
    if os.name != "nt" and info.st_mode & 0o077:
        raise BackupError("Age identity file permissions must be 0600 or stricter.")
    return path.resolve()


def _snapshot_database(source: Path, target: Path) -> dict:
    try:
        info = source.lstat()
    except OSError as exc:
        raise BackupError("Required database is missing: " + source.name) from exc
    if source.is_symlink() or not source.is_file():
        raise BackupError("Database is not a regular file: " + source.name)
    if info.st_size > MAX_DATABASE_BYTES:
        raise BackupError("Database exceeds the 20 GiB backup limit: " + source.name)
    uri = source.resolve().as_uri() + "?mode=ro"
    source_db = sqlite3.connect(uri, uri=True, timeout=30)
    target_db = sqlite3.connect(target, timeout=30)
    try:
        source_db.backup(target_db, pages=256, sleep=0.05)
        result = target_db.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError("SQLite integrity check failed for " + source.name)
    finally:
        target_db.close()
        source_db.close()
    os.chmod(target, 0o600)
    size = target.stat().st_size
    if size > MAX_DATABASE_BYTES:
        raise BackupError("Database snapshot exceeds the 20 GiB backup limit: " + source.name)
    return {"name": source.name, "size": size, "sha256": _sha256_file(target)}


def _database_sources(data_dir: Path) -> list[Path]:
    sources = []
    for name in REQUIRED_DATABASES:
        path = data_dir / name
        if not path.exists():
            raise BackupError("Required host database is missing: " + name)
        sources.append(path)
    for name in OPTIONAL_DATABASES:
        path = data_dir / name
        if path.exists():
            sources.append(path)
    return sources


def create_backup(data_dir: str | Path, backup_dir: str | Path) -> dict:
    source_root = Path(data_dir).expanduser().resolve()
    destination_root = Path(backup_dir).expanduser().resolve()
    _check_paths(source_root, destination_root)
    _check_private_directory(destination_root)
    recipient = _age_recipient()
    sources = _database_sources(source_root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_name = f"streamiov-host-{timestamp}-{uuid.uuid4().hex[:8]}.tar.gz.age"
    final_path = destination_root / backup_name

    with tempfile.TemporaryDirectory(prefix=".streamiov-backup-", dir=destination_root) as temp_name:
        temp_root = Path(temp_name)
        snapshots = temp_root / "databases"
        snapshots.mkdir(mode=0o700)
        entries = []
        for source in sources:
            entries.append(_snapshot_database(source, snapshots / source.name))
        manifest = {
            "format": "streamiov-host-backup",
            "version": 1,
            "created_at": _utc_now(),
            "databases": entries,
            "restore_mode": "staging_only",
        }
        manifest_path = temp_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        archive_path = temp_root / "backup.tar.gz"
        with tarfile.open(archive_path, "w:gz", compresslevel=6) as archive:
            archive.add(manifest_path, arcname="manifest.json", recursive=False)
            for entry in entries:
                archive.add(snapshots / entry["name"], arcname="databases/" + entry["name"], recursive=False)
        encrypted_path = temp_root / backup_name
        try:
            subprocess.run(
                [_age_binary(), "-r", recipient, "-o", str(encrypted_path), str(archive_path)],
                check=True, capture_output=True, text=True, timeout=600,
            )
        except FileNotFoundError as exc:
            raise BackupError("age is not installed. Install the free age encryption tool before enabling backups.") from exc
        except subprocess.CalledProcessError as exc:
            raise BackupError("age encryption failed: " + (exc.stderr or "no diagnostic").strip()[:240]) from exc
        if not encrypted_path.is_file() or encrypted_path.stat().st_size < 64:
            raise BackupError("age produced an empty or incomplete encrypted backup.")
        with encrypted_path.open("rb") as handle:
            if handle.read(20) != b"age-encryption.org/v1":
                raise BackupError("Encrypted backup does not have a valid age file header.")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(encrypted_path, 0o600)
        os.replace(encrypted_path, final_path)
        _fsync_directory(destination_root)

    metadata = {
        "backup_file": backup_name,
        "created_at": manifest["created_at"],
        "ciphertext_size": final_path.stat().st_size,
        "ciphertext_sha256": _sha256_file(final_path),
        "databases": [entry["name"] for entry in entries],
        "status": "encrypted_pending_restore_verification",
    }
    _atomic_json(destination_root / (backup_name + ".meta.json"), metadata)
    return metadata


def _safe_backup_file(backup_dir: Path, name: str) -> Path:
    if not isinstance(name, str) or not BACKUP_PATTERN.fullmatch(name):
        raise BackupError("Invalid backup file name.")
    path = backup_dir / name
    if path.is_symlink() or not path.is_file():
        raise BackupError("Backup file is missing or is not a regular file.")
    return path


def _decrypt_backup(backup_path: Path, temp_root: Path, identity: Path) -> Path:
    archive_path = temp_root / "decrypted.tar.gz"
    try:
        subprocess.run(
            [_age_binary(), "-d", "-i", str(identity), "-o", str(archive_path), str(backup_path)],
            check=True, capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError as exc:
        raise BackupError("age is not installed.") from exc
    except subprocess.CalledProcessError as exc:
        raise BackupError("Backup could not be decrypted. Check the owner identity key.") from exc
    if not archive_path.is_file() or archive_path.stat().st_size < 128:
        raise BackupError("Decrypted archive is empty or incomplete.")
    return archive_path


def _verify_archive(archive_path: Path, output_dir: Path) -> tuple[dict, str]:
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    seen: set[str] = set()
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > len(ALLOWED_DATABASES) + 1:
                raise BackupError("Archive contains too many files.")
            for member in members:
                if not member.isfile() or member.issym() or member.islnk():
                    raise BackupError("Archive contains a non-regular file.")
                if member.name in seen:
                    raise BackupError("Archive contains duplicate paths.")
                seen.add(member.name)
            if "manifest.json" not in seen:
                raise BackupError("Archive manifest is missing.")
            manifest_member = archive.getmember("manifest.json")
            if manifest_member.size > MAX_MANIFEST_BYTES:
                raise BackupError("Archive manifest exceeds size limit.")
            manifest_stream = archive.extractfile(manifest_member)
            if manifest_stream is None:
                raise BackupError("Archive manifest cannot be read.")
            manifest_bytes = manifest_stream.read(MAX_MANIFEST_BYTES + 1)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if manifest.get("format") != "streamiov-host-backup" or manifest.get("version") != 1:
                raise BackupError("Unsupported backup format.")
            entries = manifest.get("databases")
            if not isinstance(entries, list) or not entries:
                raise BackupError("Backup manifest contains no databases.")
            expected_paths = {"manifest.json"}
            entry_names = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise BackupError("Invalid database entry in manifest.")
                name, size, expected_hash = entry.get("name"), entry.get("size"), entry.get("sha256")
                if name not in ALLOWED_DATABASES or name in entry_names:
                    raise BackupError("Unexpected or duplicate database in backup.")
                if type(size) is not int or not 1 <= size <= MAX_DATABASE_BYTES:
                    raise BackupError("Invalid database size in backup manifest.")
                if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
                    raise BackupError("Invalid database hash in backup manifest.")
                entry_names.add(name)
                expected_paths.add("databases/" + name)
                member = archive.getmember("databases/" + name)
                if member.size != size:
                    raise BackupError("Database size does not match manifest: " + name)
                source = archive.extractfile(member)
                if source is None:
                    raise BackupError("Database file cannot be read: " + name)
                target = output_dir / name
                digest = hashlib.sha256()
                written = 0
                with target.open("xb") as destination:
                    os.chmod(target, 0o600)
                    while True:
                        chunk = source.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > size or written > MAX_DATABASE_BYTES:
                            raise BackupError("Database exceeds declared size: " + name)
                        digest.update(chunk)
                        destination.write(chunk)
                    destination.flush()
                    os.fsync(destination.fileno())
                if written != size or digest.hexdigest() != expected_hash:
                    raise BackupError("Database hash or size verification failed: " + name)
                connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True, timeout=20)
                try:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                    if not result or result[0] != "ok":
                        raise BackupError("Restored SQLite integrity check failed: " + name)
                finally:
                    connection.close()
            if entry_names.intersection(REQUIRED_DATABASES) != set(REQUIRED_DATABASES):
                raise BackupError("Backup is missing one or more required host databases.")
            if seen != expected_paths:
                raise BackupError("Archive contains unlisted files or paths.")
            return manifest, hashlib.sha256(manifest_bytes).hexdigest()
    except (tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError, KeyError, OSError, sqlite3.Error) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("Backup archive is invalid or cannot be read.") from exc


def verify_backup(backup_dir: str | Path, name: str, identity_file: str | None = None) -> dict:
    root = Path(backup_dir).expanduser().resolve()
    backup_path = _safe_backup_file(root, name)
    metadata_path = root / (name + ".meta.json")
    if metadata_path.is_symlink() or not metadata_path.is_file():
        raise BackupError("Backup metadata is missing.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    actual_hash = _sha256_file(backup_path)
    if metadata.get("ciphertext_sha256") != actual_hash:
        raise BackupError("Encrypted backup checksum does not match its metadata.")
    identity = _identity_path(identity_file)
    with tempfile.TemporaryDirectory(prefix="streamiov-verify-") as temp_name:
        temp_root = Path(temp_name)
        archive_path = _decrypt_backup(backup_path, temp_root, identity)
        output_dir = temp_root / "verified-databases"
        manifest, manifest_hash = _verify_archive(archive_path, output_dir)
    verified = {
        "backup_file": name,
        "ciphertext_sha256": actual_hash,
        "manifest_sha256": manifest_hash,
        "verified_at": _utc_now(),
        "database_count": len(manifest["databases"]),
        "status": "verified",
    }
    _atomic_json(root / (name + ".verified.json"), verified)
    return verified


def restore_to_staging(backup_dir: str | Path, name: str, identity_file: str | None = None) -> dict:
    root = Path(backup_dir).expanduser().resolve()
    backup_path = _safe_backup_file(root, name)
    metadata_path = root / (name + ".meta.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("ciphertext_sha256") != _sha256_file(backup_path):
        raise BackupError("Encrypted backup checksum does not match its metadata.")
    identity = _identity_path(identity_file)
    staging_root = root / "restore-staging"
    _check_private_directory(staging_root)
    stage = staging_root / (name.removesuffix(".tar.gz.age") + "-" + uuid.uuid4().hex[:8])
    with tempfile.TemporaryDirectory(prefix="streamiov-restore-") as temp_name:
        archive_path = _decrypt_backup(backup_path, Path(temp_name), identity)
        try:
            manifest, manifest_hash = _verify_archive(archive_path, stage)
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise
    _atomic_json(stage / "RESTORE-MANIFEST.json", {
        "backup_file": name,
        "manifest_sha256": manifest_hash,
        "staged_at": _utc_now(),
        "status": "verified_staging_only",
        "live_databases_modified": False,
    })
    return {
        "staging_directory": str(stage),
        "database_count": len(manifest["databases"]),
        "status": "verified_staging_only",
        "live_databases_modified": False,
    }


def list_backups(backup_dir: str | Path) -> list[dict]:
    root = Path(backup_dir).expanduser().resolve()
    if not root.exists():
        return []
    result = []
    for path in sorted(root.glob("streamiov-host-*.tar.gz.age"), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file() or not BACKUP_PATTERN.fullmatch(path.name):
            continue
        metadata_path = root / (path.name + ".meta.json")
        verified_path = root / (path.name + ".verified.json")
        metadata = {}
        verified = False
        try:
            if metadata_path.is_file() and not metadata_path.is_symlink():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if verified_path.is_file() and not verified_path.is_symlink():
                proof = json.loads(verified_path.read_text(encoding="utf-8"))
                verified = proof.get("status") == "verified" and proof.get("ciphertext_sha256") == _sha256_file(path)
        except (OSError, json.JSONDecodeError):
            verified = False
        result.append({
            "backup_file": path.name,
            "size": path.stat().st_size,
            "created_at": metadata.get("created_at"),
            "status": "verified" if verified else metadata.get("status", "unknown"),
        })
    return result


def prune_backups(backup_dir: str | Path, keep_days: int = 30, *, now: float | None = None) -> dict:
    if type(keep_days) is not int or not 1 <= keep_days <= 3650:
        raise BackupError("Retention must be between 1 and 3650 days.")
    root = Path(backup_dir).expanduser().resolve()
    backups = list_backups(root)
    verified = [item for item in backups if item["status"] == "verified"]
    if len(verified) <= 1:
        return {"deleted": [], "retained": len(backups), "reason": "last_verified_backup_protected"}
    current = time.time() if now is None else now
    cutoff = current - keep_days * 86400
    newest = max(verified, key=lambda item: item["created_at"] or "")
    deleted = []
    for item in verified:
        if item["backup_file"] == newest["backup_file"]:
            continue
        created = item["created_at"]
        try:
            created_at = datetime.fromisoformat(created).timestamp()
        except (TypeError, ValueError):
            continue
        if created_at >= cutoff:
            continue
        name = item["backup_file"]
        backup_path = _safe_backup_file(root, name)
        backup_path.unlink()
        for suffix in (".meta.json", ".verified.json"):
            sidecar = root / (name + suffix)
            if sidecar.is_file() and not sidecar.is_symlink():
                sidecar.unlink()
        deleted.append(name)
    if deleted:
        _fsync_directory(root)
    return {"deleted": deleted, "retained": len(backups) - len(deleted)}


def _default_paths() -> tuple[Path, Path]:
    data = Path(os.environ.get("STREAMIOV_DATA_DIR", "~/.local/share/streamiov-host")).expanduser()
    backups = Path(os.environ.get("STREAMIOV_BACKUP_DIR", "/var/backups/streamiov")).expanduser()
    return data, backups


def main(argv: list[str] | None = None) -> int:
    data_default, backup_default = _default_paths()
    parser = argparse.ArgumentParser(description="Encrypted Streamiov host database backup and safe restore staging.")
    parser.add_argument("--data-dir", type=Path, default=data_default)
    parser.add_argument("--backup-dir", type=Path, default=backup_default)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="Create an age-encrypted, consistent SQLite snapshot.")
    commands.add_parser("list", help="List encrypted backups and owner verification state.")
    verify = commands.add_parser("verify", help="Decrypt and verify a backup using the owner identity.")
    verify.add_argument("name")
    verify.add_argument("--identity")
    restore = commands.add_parser("restore-stage", help="Verify and extract into an isolated staging directory; never overwrites live data.")
    restore.add_argument("name")
    restore.add_argument("--identity")
    prune = commands.add_parser("prune", help="Remove only old, owner-verified backups; preserve the last verified backup.")
    prune.add_argument("--keep-days", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create_backup(args.data_dir, args.backup_dir)
        elif args.command == "list":
            result = {"backups": list_backups(args.backup_dir)}
        elif args.command == "verify":
            result = verify_backup(args.backup_dir, args.name, args.identity)
        elif args.command == "restore-stage":
            result = restore_to_staging(args.backup_dir, args.name, args.identity)
        elif args.command == "prune":
            result = prune_backups(args.backup_dir, args.keep_days)
        else:
            raise BackupError("Unknown command.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BackupError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
