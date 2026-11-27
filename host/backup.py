from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"
SCHEDULE_STATE_NAME = "backup-schedule.json"
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "infrastructure" / "backup" / "core" / "backup-policy.json"
BACKUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SCHEDULE_ROOT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,48}$")
DATABASES = (
    ("accounts.sqlite3", "databases/accounts.sqlite3"),
    ("forum.sqlite3", "databases/forum.sqlite3"),
    ("streamiov-data.sqlite3", "databases/streamiov-data.sqlite3"),
    ("ai_tasks.sqlite3", "databases/ai_tasks.sqlite3"),
    ("events.sqlite3", "databases/events.sqlite3"),
    ("wishbox.sqlite3", "databases/wishbox.sqlite3"),
    ("music.sqlite3", "databases/music.sqlite3"),
    ("platform_connections.sqlite3", "databases/platform_connections.sqlite3"),
)
SECRETS = (("oauth-token.key", "secrets/oauth-token.key"),)
ALLOWED_PATHS = {relative for _, relative in DATABASES} | {relative for _, relative in SECRETS}


class BackupError(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise BackupError("Manifest path must be a string.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise BackupError(f"Unsafe manifest path: {value}")
    return path


def _check_backup_path(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.is_symlink() or not resolved.is_dir():
        raise BackupError(f"Backup directory does not exist: {resolved}")
    return resolved


def _read_manifest(backup_dir: Path) -> dict:
    manifest_path = backup_dir / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BackupError(f"Backup manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("Backup manifest is unreadable.") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_VERSION:
        raise BackupError("Unsupported backup manifest version.")
    if not isinstance(manifest.get("created_at"), str) or not isinstance(manifest.get("host_version"), str):
        raise BackupError("Backup manifest metadata is invalid.")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise BackupError("Backup manifest file list is invalid.")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise BackupError("Backup manifest contains an invalid entry.")
        relative = _relative_path(entry.get("path"))
        name = str(relative)
        if name not in ALLOWED_PATHS or name in seen:
            raise BackupError(f"Backup manifest contains a duplicate or unknown path: {name}")
        seen.add(name)
        if entry.get("kind") not in {"database", "secret"}:
            raise BackupError(f"Backup manifest has an invalid file kind: {name}")
        if not isinstance(entry.get("present"), bool):
            raise BackupError(f"Backup manifest has an invalid presence value: {name}")
        if entry["present"]:
            if not isinstance(entry.get("size"), int) or entry["size"] < 0:
                raise BackupError(f"Backup manifest has an invalid file size: {name}")
            if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                raise BackupError(f"Backup manifest has an invalid checksum: {name}")
    if seen != ALLOWED_PATHS:
        raise BackupError("Backup manifest does not list every required path.")
    return manifest


def create_backup(data_dir: Path, backup_root: Path | None = None) -> dict:
    source_dir = Path(data_dir).expanduser().resolve()
    root = (Path(backup_root).expanduser().resolve()
            if backup_root is not None else source_dir / "backups")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = "streamiov-host-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    backup_dir = root / name
    backup_dir.mkdir(mode=0o700)
    (backup_dir / "databases").mkdir(mode=0o700)
    (backup_dir / "secrets").mkdir(mode=0o700)
    files = []
    for source_name, relative in DATABASES:
        source = source_dir / source_name
        if source.is_symlink():
            raise BackupError(f"Refusing to back up a symlink: {source_name}")
        entry = {"path": relative, "kind": "database", "source": source_name, "present": False}
        if source.exists():
            if not source.is_file():
                raise BackupError(f"Backup source is not a regular file: {source_name}")
            destination = backup_dir / relative
            source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
            destination_connection = sqlite3.connect(destination)
            try:
                source_connection.backup(destination_connection)
            finally:
                source_connection.close()
                destination_connection.close()
            os.chmod(destination, 0o600)
            entry["present"] = True
            entry["size"] = destination.stat().st_size
            entry["sha256"] = _sha256(destination)
        files.append(entry)
    for source_name, relative in SECRETS:
        source = source_dir / source_name
        if source.is_symlink():
            raise BackupError(f"Refusing to back up a symlink: {source_name}")
        entry = {"path": relative, "kind": "secret", "source": source_name, "present": False}
        if source.exists():
            if not source.is_file():
                raise BackupError(f"Backup source is not a regular file: {source_name}")
            if source.stat().st_mode & 0o077:
                raise BackupError(f"Secret file has permissive permissions: {source_name}")
            destination = backup_dir / relative
            shutil.copyfile(source, destination)
            os.chmod(destination, 0o600)
            entry["present"] = True
            entry["size"] = destination.stat().st_size
            entry["sha256"] = _sha256(destination)
        files.append(entry)
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host_version": "local-core-backup-v1",
        "files": files,
    }
    manifest_path = backup_dir / MANIFEST_NAME
    temporary_manifest = backup_dir / (MANIFEST_NAME + ".tmp")
    temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
    os.chmod(temporary_manifest, 0o600)
    os.replace(temporary_manifest, manifest_path)
    return {"ok": True, "name": name, "path": str(backup_dir), "manifest": manifest}


def list_backups(backup_root: Path) -> list[dict]:
    root = Path(backup_root).expanduser().resolve()
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise BackupError(f"Backup root is not a directory: {root}")
    entries = []
    for candidate in sorted(root.iterdir()):
        if not BACKUP_NAME_PATTERN.fullmatch(candidate.name) or candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            manifest = _read_manifest(candidate)
        except BackupError as exc:
            entries.append({"name": candidate.name, "ok": False, "error": str(exc)})
            continue
        entries.append({
            "name": candidate.name,
            "ok": True,
            "created_at": manifest["created_at"],
            "files": sum(1 for item in manifest["files"] if item["present"]),
        })
    return entries


def prune_backups(backup_root: Path, keep: int = 3) -> dict:
    if not isinstance(keep, int) or isinstance(keep, bool) or keep < 1:
        raise BackupError("Backup retention must keep at least one backup.")
    root = Path(backup_root).expanduser().resolve()
    entries = list_backups(root)
    valid = sorted((entry for entry in entries if entry["ok"]),
                   key=lambda entry: (entry["created_at"], entry["name"]), reverse=True)
    kept = [entry["name"] for entry in valid[:keep]]
    deleted = []
    for entry in valid[keep:]:
        candidate = root / entry["name"]
        if candidate.is_symlink() or not candidate.is_dir():
            raise BackupError(f"Refusing to prune an unsafe backup path: {candidate}")
        shutil.rmtree(candidate)
        deleted.append(entry["name"])
    return {
        "ok": True,
        "root": str(root),
        "keep": keep,
        "kept": kept,
        "deleted": deleted,
        "invalid": [entry["name"] for entry in entries if not entry["ok"]],
    }


def verify_backup(backup_dir: Path) -> dict:
    resolved = _check_backup_path(backup_dir)
    manifest = _read_manifest(resolved)
    verified = []
    for entry in manifest["files"]:
        name = entry["path"]
        relative = _relative_path(name)
        candidate = resolved / relative
        if not entry["present"]:
            if candidate.exists():
                raise BackupError(f"Absent manifest entry exists on disk: {name}")
            verified.append({"path": name, "present": False})
            continue
        if candidate.is_symlink() or not candidate.is_file():
            raise BackupError(f"Backup file is missing or unsafe: {name}")
        size = candidate.stat().st_size
        checksum = _sha256(candidate)
        if size != entry["size"] or checksum != entry["sha256"]:
            raise BackupError(f"Backup file failed checksum verification: {name}")
        if entry["kind"] == "secret" and candidate.stat().st_mode & 0o077:
            raise BackupError(f"Secret backup file has permissive permissions: {name}")
        if entry["kind"] == "database":
            try:
                connection = sqlite3.connect(f"file:{candidate}?mode=ro", uri=True)
                try:
                    result = connection.execute("PRAGMA quick_check(1)").fetchone()
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                raise BackupError(f"Database backup is unreadable: {name}") from exc
            if result is None or result[0] != "ok":
                raise BackupError(f"Database backup failed integrity check: {name}")
        verified.append({"path": name, "present": True, "size": size, "sha256": checksum})
    return {
        "ok": True,
        "name": resolved.name,
        "created_at": manifest["created_at"],
        "host_version": manifest["host_version"],
        "files": verified,
    }


def restore_backup(backup_dir: Path, data_dir: Path, force: bool = False) -> dict:
    report = verify_backup(backup_dir)
    source_dir = _check_backup_path(backup_dir)
    target = Path(data_dir).expanduser().resolve()
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise BackupError(f"Restore target is not a directory: {target}")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = _read_manifest(source_dir)
    restore_map = {source: entry["path"] for source, entry in
                   ((source, next((item for item in manifest["files"]
                                   if item.get("source") == source and item["present"]), None))
                    for source, _ in (*DATABASES, *SECRETS)) if entry is not None}
    for source_name, relative in restore_map.items():
        destination = target / source_name
        if destination.is_symlink():
            raise BackupError(f"Refusing to replace a symlink: {source_name}")
        if destination.exists() and not force:
            raise BackupError(f"Restore target already exists: {source_name}; use --backup-force to replace it.")
    stage = target / (".streamiov-restore-" + secrets.token_hex(8))
    rollback = target / (".streamiov-rollback-" + secrets.token_hex(8))
    stage.mkdir(mode=0o700)
    rollback.mkdir(mode=0o700)
    staged_files = []
    rollback_files = []
    restored_sources = []
    try:
        for source_name, relative in restore_map.items():
            source = source_dir / _relative_path(relative)
            staged = stage / relative
            staged.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, staged)
            os.chmod(staged, 0o600)
            staged_files.append((source_name, staged))
            destination = target / source_name
            if destination.exists():
                saved = rollback / relative
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(destination, saved)
                rollback_files.append((source_name, saved))
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = destination.with_name(destination.name + suffix)
                if sidecar.exists():
                    if sidecar.is_symlink():
                        raise BackupError(f"Refusing to replace a symlink: {sidecar.name}")
                    saved = rollback / (relative + suffix)
                    saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copyfile(sidecar, saved)
                    rollback_files.append((sidecar.name, saved))
        for source_name, staged in staged_files:
            destination = target / source_name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(staged, destination)
            os.chmod(destination, 0o600)
            restored_sources.append(source_name)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = destination.with_name(destination.name + suffix)
                if sidecar.exists() and not sidecar.is_symlink():
                    sidecar.unlink()
    except Exception:
        preserved = {name for name, _ in rollback_files}
        for name, saved in reversed(rollback_files):
            os.replace(saved, target / name)
        for name in restored_sources:
            destination = target / name
            if name not in preserved and destination.exists():
                destination.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(rollback, ignore_errors=True)
    return {"ok": True, **report, "restored_files": restored_sources}


def load_backup_policy(policy_path: Path | str | None = None) -> dict:
    path = Path(policy_path).expanduser().resolve() if policy_path else DEFAULT_POLICY_PATH
    policy = {
        "enabled": False,
        "interval_seconds": 3600,
        "keep": 3,
        "backup_root": "backups",
        "source": str(path),
        "error": None,
    }
    try:
        if path.is_symlink() or not path.is_file():
            raise BackupError("Backup policy file is missing or unsafe.")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, BackupError) as exc:
        policy["error"] = "Backup policy is unreadable: " + str(exc)[:160]
        return policy
    if not isinstance(raw, dict):
        policy["error"] = "Backup policy must be an object."
        return policy
    schedule = raw.get("schedule")
    if not isinstance(schedule, dict):
        policy["error"] = "Backup policy has no local schedule."
        return policy
    enabled = schedule.get("enabled", False)
    interval = schedule.get("interval_minutes", 60)
    keep = schedule.get("keep", 3)
    root = schedule.get("backup_root", "backups")
    if not isinstance(enabled, bool):
        policy["error"] = "Backup schedule enabled flag must be boolean."
        return policy
    if not isinstance(interval, int) or isinstance(interval, bool) or not 5 <= interval <= 10080:
        policy["error"] = "Backup schedule interval must be 5 to 10080 minutes."
        return policy
    if not isinstance(keep, int) or isinstance(keep, bool) or not 1 <= keep <= 30:
        policy["error"] = "Backup schedule retention must keep 1 to 30 backups."
        return policy
    if not isinstance(root, str) or not SCHEDULE_ROOT_PATTERN.fullmatch(root) or root in {".", ".."}:
        policy["error"] = "Backup schedule root must be a simple local directory name."
        return policy
    policy.update({
        "enabled": enabled,
        "interval_seconds": interval * 60,
        "keep": keep,
        "backup_root": root,
        "error": None,
    })
    return policy


class BackupScheduler:
    def __init__(self, data_dir: Path, policy_path: Path | str | None = None,
                 policy: dict | None = None, now=None):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.policy = dict(policy) if policy is not None else load_backup_policy(policy_path)
        self.root = self.data_dir / str(self.policy.get("backup_root", "backups"))
        self.state_path = self.root / SCHEDULE_STATE_NAME
        self.now = now if callable(now) else time.time
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    def _default_state(self) -> dict:
        return {
            "schema_version": 1,
            "last_run_at": None,
            "last_success_at": None,
            "next_run_at": None,
            "last_result": {},
            "last_error": None,
            "state_error": None,
            "run_count": 0,
            "failure_count": 0,
        }

    def _load_state(self) -> dict:
        state = self._default_state()
        if not self.state_path.exists():
            return state
        if self.state_path.is_symlink() or not self.state_path.is_file():
            state["state_error"] = "Backup schedule state is unsafe."
            return state
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state["state_error"] = "Backup schedule state is unreadable."
            return state
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            state["state_error"] = "Backup schedule state has an unsupported version."
            return state
        for key in ("last_run_at", "last_success_at", "next_run_at"):
            value = raw.get(key)
            if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
                state[key] = value
            else:
                state["state_error"] = "Backup schedule timestamps are invalid."
                return state
        for key in ("run_count", "failure_count"):
            value = raw.get(key, 0)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                state[key] = value
            else:
                state["state_error"] = "Backup schedule counters are invalid."
                return state
        last_result = raw.get("last_result", {})
        if isinstance(last_result, dict) and len(last_result) <= 12:
            state["last_result"] = {str(key): str(value)[:120] for key, value in last_result.items()}
        else:
            state["state_error"] = "Backup schedule result is invalid."
            return state
        error = raw.get("last_error")
        state["last_error"] = str(error)[:240] if isinstance(error, str) else None
        return state

    def _write_state(self, state: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.root / (SCHEDULE_STATE_NAME + "." + secrets.token_hex(6) + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.state_path)
        os.chmod(self.state_path, 0o600)

    @staticmethod
    def _iso(value) -> str | None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    def status(self) -> dict:
        with self._lock:
            state = self._load_state()
            current = self.now()
            next_run = state.get("next_run_at")
            return {
                "ok": self.policy.get("error") is None and state.get("state_error") is None,
                "policy": {
                    "enabled": self.policy.get("enabled") is True,
                    "interval_seconds": self.policy.get("interval_seconds"),
                    "keep": self.policy.get("keep"),
                    "backup_root": self.policy.get("backup_root"),
                    "error": self.policy.get("error"),
                },
                "state": {
                    "last_run_at": self._iso(state.get("last_run_at")),
                    "last_success_at": self._iso(state.get("last_success_at")),
                    "next_run_at": self._iso(next_run),
                    "last_result": state.get("last_result", {}),
                    "last_error": state.get("last_error"),
                    "state_error": state.get("state_error"),
                    "run_count": state.get("run_count", 0),
                    "failure_count": state.get("failure_count", 0),
                },
                "due_now": next_run is None or current >= next_run,
                "production_status": "NOT_VERIFIED",
            }

    def run_once(self, force: bool = False, at: float | None = None) -> dict:
        with self._lock:
            current = self.now() if at is None else float(at)
            state = self._load_state()
            next_run = state.get("next_run_at")
            if not force and next_run is not None and current < next_run:
                return {"ok": True, "ran": False, "reason": "not_due", "status": self.status()}
            if self.policy.get("error"):
                return {"ok": False, "ran": True, "error": self.policy["error"], "status": self.status()}
            if state.get("state_error"):
                return {"ok": False, "ran": True, "error": state["state_error"], "status": self.status()}
            interval = int(self.policy.get("interval_seconds", 3600))
            keep = int(self.policy.get("keep", 3))
            state["last_run_at"] = current
            state["next_run_at"] = current + interval
            state["run_count"] = int(state.get("run_count", 0)) + 1
            try:
                created = create_backup(self.data_dir, self.root)
                verified = verify_backup(Path(created["path"]))
                pruned = prune_backups(self.root, keep)
                report = {
                    "ok": True,
                    "ran": True,
                    "backup": created["name"],
                    "verified": verified["ok"],
                    "keep": keep,
                    "kept": pruned["kept"],
                    "deleted": pruned["deleted"],
                    "invalid": pruned["invalid"],
                    "next_run_at": self._iso(state["next_run_at"]),
                }
                state["last_success_at"] = current
                state["last_error"] = None
                state["last_result"] = {
                    "ok": True, "backup": created["name"], "verified": True,
                    "kept": len(pruned["kept"]), "deleted": len(pruned["deleted"]),
                }
            except (BackupError, OSError, sqlite3.Error) as exc:
                message = str(exc)[:240]
                report = {"ok": False, "ran": True, "error": message,
                          "next_run_at": self._iso(state["next_run_at"])}
                state["failure_count"] = int(state.get("failure_count", 0)) + 1
                state["last_error"] = message
                state["last_result"] = {"ok": False, "error": message}
            self._write_state(state)
            report["status"] = self.status()
            return report

    def start(self) -> bool:
        with self._lock:
            if self.policy.get("enabled") is not True or self.policy.get("error"):
                return False
            if self._thread is not None and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="streamiov-backup-schedule", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _loop(self) -> None:
        interval = max(5, min(60, int(self.policy.get("interval_seconds", 3600))))
        while not self._stop.wait(interval):
            try:
                self.run_once()
            except Exception:
                continue
