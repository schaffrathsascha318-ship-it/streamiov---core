from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ai.runtime.project_tools import (
    DENIED_FILE_NAMES,
    DENIED_PARTS,
    DENIED_PATH_PREFIXES,
    DENIED_SUFFIXES,
    ToolError,
    _atomic_replace_text,
    _locked_path,
)

WORKSPACE_ROOT_NAME = ".streamiov-task-workspaces"
COPY_SKIP_DIRS = frozenset({
    ".git",
    ".streamiov",
    WORKSPACE_ROOT_NAME,
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
})
WORKSPACE_STATUSES = frozenset({"active", "ready", "integrated", "blocked", "orphaned"})
INTEGRATION_STATUSES = frozenset({"pending", "verified", "integrated", "conflict"})
CANDIDATE_STATUSES = frozenset({"building", "verified", "integrated", "blocked"})


class TaskWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskWorkspace:
    task_id: str
    mission_id: str
    cycle: int
    source_root: str
    path: str
    status: str
    integration_status: str
    owner_worker_id: str
    lease_until: float | None
    created_at: float
    updated_at: float


def _text_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    if path.is_symlink():
        raise TaskWorkspaceError("Symlink files cannot be used as workspace changes.")
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_relative(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise TaskWorkspaceError("A valid relative project path is required.")
    rel = PurePosixPath(raw)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise TaskWorkspaceError("Workspace paths must be normalized relative paths without traversal.")
    lowered = [part.lower() for part in rel.parts]
    if any(
        part in DENIED_PARTS
        or part == WORKSPACE_ROOT_NAME
        or part.startswith(".env")
        or any(word in part for word in ("secret", "credential", "access-token", "refresh-token"))
        for part in lowered
    ):
        raise TaskWorkspaceError("Workspace access to protected paths and secret-like files is denied.")
    if rel.name.lower() in DENIED_FILE_NAMES or rel.suffix.lower() in DENIED_SUFFIXES:
        raise TaskWorkspaceError("Workspace access to protected paths and secret-like files is denied.")
    normalized = rel.as_posix().lower()
    if any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in DENIED_PATH_PREFIXES
    ):
        raise TaskWorkspaceError("Workspace access to protected paths and secret-like files is denied.")
    return rel


def _safe_target(root: Path, rel: PurePosixPath) -> Path:
    candidate = root.joinpath(*rel.parts)
    if candidate.is_symlink():
        raise TaskWorkspaceError("Symlink access is denied in task workspaces.")
    parent = candidate.parent
    while parent != root:
        if root not in parent.parents:
            raise TaskWorkspaceError("Workspace path escapes its root.")
        if parent.is_symlink():
            raise TaskWorkspaceError("Symlink access is denied in task workspaces.")
        parent = parent.parent
    return candidate


def _denied_file_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in DENIED_FILE_NAMES
        or lowered.startswith(".env")
        or any(word in lowered for word in ("secret", "credential", "access-token", "refresh-token"))
        or PurePosixPath(name).suffix.lower() in DENIED_SUFFIXES
    )


class TaskWorkspaceStore:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise TaskWorkspaceError("Task workspace database must not be a symlink.")
        self.workspace_root = self.path.parent / WORKSPACE_ROOT_NAME
        if self.workspace_root.is_symlink():
            raise TaskWorkspaceError("Task workspace root must not be a symlink.")
        self.workspace_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS development_task_workspaces (
                    task_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    cycle INTEGER NOT NULL,
                    source_root TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','ready','integrated','blocked','orphaned')),
                    integration_status TEXT NOT NULL CHECK(integration_status IN ('pending','verified','integrated','conflict')),
                    owner_worker_id TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS development_task_workspace_changes (
                    task_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    base_sha256 TEXT NOT NULL,
                    new_sha256 TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','applied','integrated','conflict')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(task_id, relative_path)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS development_task_workspace_candidates (
                    candidate_key TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    cycle INTEGER NOT NULL,
                    source_root TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('building','verified','integrated','blocked')),
                    conflict TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_workspaces_mission
                ON development_task_workspaces(mission_id, cycle, status)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_workspace_changes_task
                ON development_task_workspace_changes(task_id, status)
            """)

    def _row(self, task_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT * FROM development_task_workspaces WHERE task_id=?", (task_id,)
            ).fetchone()

    def _workspace_path(self, task_id: str) -> Path:
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        path = self.workspace_root / digest[:2] / digest
        if path.is_symlink():
            raise TaskWorkspaceError("Task workspace path must not be a symlink.")
        return path

    def _candidate_path(self, candidate_key: str) -> Path:
        digest = hashlib.sha256(candidate_key.encode("utf-8")).hexdigest()
        path = self.workspace_root / "candidates" / digest[:2] / digest
        if path.is_symlink():
            raise TaskWorkspaceError("Candidate workspace path must not be a symlink.")
        return path

    def _copy_source(self, source_root: Path, destination: Path) -> None:
        if destination.is_symlink():
            raise TaskWorkspaceError("Task workspace destination must not be a symlink.")
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(mode=0o700, parents=True)
        excluded_files = {
            self.path.name,
            self.path.name + "-wal",
            self.path.name + "-shm",
        }
        for current, directories, files in os.walk(source_root):
            directories[:] = sorted(
                name for name in directories
                if name not in COPY_SKIP_DIRS and not _denied_file_name(name)
            )
            current_path = Path(current)
            relative = current_path.relative_to(source_root)
            target_dir = destination.joinpath(*relative.parts) if relative.parts else destination
            target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            for name in sorted(files):
                if name in excluded_files or _denied_file_name(name):
                    continue
                source_file = current_path / name
                if source_file.is_symlink() or not source_file.is_file():
                    continue
                target_file = target_dir / name
                try:
                    os.link(source_file, target_file)
                except OSError:
                    shutil.copy2(source_file, target_file)

    def _promote_recovered_changes(self, workspace_path: Path, task_id: str) -> None:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT relative_path,new_sha256 FROM development_task_workspace_changes "
                "WHERE task_id=? AND status='pending'", (task_id,)
            ).fetchall()
        for row in rows:
            rel = _validate_relative(row["relative_path"])
            target = _safe_target(workspace_path, rel)
            if target.is_file() and _file_digest(target) == row["new_sha256"]:
                with closing(self._connect()) as db, db:
                    db.execute(
                        "UPDATE development_task_workspace_changes SET status='applied',updated_at=? "
                        "WHERE task_id=? AND relative_path=? AND status='pending'",
                        (time.time(), task_id, row["relative_path"]),
                    )

    def _apply_changes(self, workspace_path: Path, task_ids: list[str], statuses: tuple[str, ...]) -> None:
        if not task_ids:
            return
        markers = ",".join("?" for _ in task_ids)
        status_markers = ",".join("?" for _ in statuses)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT * FROM development_task_workspace_changes "
                f"WHERE task_id IN ({markers}) AND status IN ({status_markers}) "
                f"ORDER BY task_id,relative_path",
                (*task_ids, *statuses),
            ).fetchall()
        for row in rows:
            rel = _validate_relative(row["relative_path"])
            target = _safe_target(workspace_path, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            with _locked_path(target, owner={"task_id": "workspace-recovery"}):
                _atomic_replace_text(target, row["content"])

    def ensure_workspace(
        self,
        task_id: str,
        mission_id: str,
        cycle: int,
        source_root: str | Path,
        worker_id: str,
        lease_seconds: int,
    ) -> tuple[Path, bool]:
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128:
            raise TaskWorkspaceError("Task ID must be 1–128 characters.")
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise TaskWorkspaceError("Mission ID is required.")
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0:
            raise TaskWorkspaceError("Mission cycle must be a non-negative integer.")
        source = Path(source_root).resolve()
        if not source.is_dir() or source.is_symlink():
            raise TaskWorkspaceError("Workspace source root must be a real directory.")
        path = self._workspace_path(task_id)
        now = time.time()
        previous = self._row(task_id)
        rebuilt = previous is None or not Path(previous["workspace_path"]).is_dir()
        source_changed = previous is not None and previous["source_root"] != str(source)
        rebuilt = rebuilt or source_changed
        if previous is None:
            with closing(self._connect()) as db, db:
                db.execute(
                    "INSERT INTO development_task_workspaces "
                    "(task_id,mission_id,cycle,source_root,workspace_path,status,integration_status,"
                    "owner_worker_id,lease_until,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'active','pending',?,?,?,?)",
                    (task_id, mission_id, cycle, str(source), str(path), worker_id, now + lease_seconds, now, now),
                )
        else:
            with closing(self._connect()) as db, db:
                db.execute(
                    "UPDATE development_task_workspaces SET source_root=?,workspace_path=?,status='active',"
                    "integration_status=CASE WHEN integration_status='integrated' THEN 'pending' ELSE integration_status END,"
                    "owner_worker_id=?,lease_until=?,updated_at=? WHERE task_id=?",
                    (str(source), str(path), worker_id, now + lease_seconds, now, task_id),
                )
        if rebuilt:
            self._copy_source(source, path)
            self._promote_recovered_changes(path, task_id)
            self._apply_changes(path, [task_id], ("applied",))
        return path, rebuilt

    def begin_change(self, task_id: str, relative_path: str, base_sha256: str, content: str) -> None:
        rel = _validate_relative(relative_path)
        if not isinstance(content, str) or len(content.encode("utf-8")) > 200_000:
            raise TaskWorkspaceError("Workspace changes must be text no larger than 200 KB.")
        row = self._row(task_id)
        if row is None or row["status"] in {"integrated", "blocked"}:
            raise TaskWorkspaceError("This task has no active writable workspace.")
        now = time.time()
        with closing(self._connect()) as db, db:
            existing = db.execute(
                "SELECT base_sha256 FROM development_task_workspace_changes WHERE task_id=? AND relative_path=?",
                (task_id, rel.as_posix()),
            ).fetchone()
            base = existing["base_sha256"] if existing else base_sha256
            db.execute(
                "INSERT INTO development_task_workspace_changes "
                "(task_id,relative_path,base_sha256,new_sha256,content,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'applied',?,?) "
                "ON CONFLICT(task_id,relative_path) DO UPDATE SET "
                "new_sha256=excluded.new_sha256,content=excluded.content,status='applied',updated_at=excluded.updated_at",
                (task_id, rel.as_posix(), base, _text_digest(content), content, now, now),
            )

    def complete_change(self, task_id: str, relative_path: str, new_sha256: str) -> None:
        rel = _validate_relative(relative_path)
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "UPDATE development_task_workspace_changes SET updated_at=? "
                "WHERE task_id=? AND relative_path=? AND new_sha256=?",
                (time.time(), task_id, rel.as_posix(), new_sha256),
            )
            if cursor.rowcount != 1:
                raise TaskWorkspaceError("Workspace change could not be committed atomically.")

    def cancel_change(self, task_id: str, relative_path: str, new_sha256: str | None = None) -> None:
        rel = _validate_relative(relative_path)
        with closing(self._connect()) as db, db:
            if new_sha256 is None:
                db.execute(
                    "DELETE FROM development_task_workspace_changes WHERE task_id=? AND relative_path=?",
                    (task_id, rel.as_posix()),
                )
            else:
                db.execute(
                    "DELETE FROM development_task_workspace_changes "
                    "WHERE task_id=? AND relative_path=? AND new_sha256=?",
                    (task_id, rel.as_posix(), new_sha256),
                )

    def change_count(self, task_id: str) -> int:
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT COUNT(*) FROM development_task_workspace_changes WHERE task_id=? AND status!='pending'",
                (task_id,),
            ).fetchone()[0]

    def mark_task_status(self, task_id: str, status: str, integration_status: str | None = None) -> None:
        if status not in WORKSPACE_STATUSES:
            raise TaskWorkspaceError("Unsupported task workspace status.")
        if integration_status is not None and integration_status not in INTEGRATION_STATUSES:
            raise TaskWorkspaceError("Unsupported workspace integration status.")
        with closing(self._connect()) as db, db:
            if integration_status is None:
                cursor = db.execute(
                    "UPDATE development_task_workspaces SET status=?,updated_at=? WHERE task_id=?",
                    (status, time.time(), task_id),
                )
            else:
                cursor = db.execute(
                    "UPDATE development_task_workspaces SET status=?,integration_status=?,updated_at=? WHERE task_id=?",
                    (status, integration_status, time.time(), task_id),
                )
            if cursor.rowcount != 1:
                raise TaskWorkspaceError("Task workspace was not found.")

    def apply_dependency_changes(self, workspace_path: Path, dependency_task_ids: tuple[str, ...]) -> None:
        self._apply_changes(workspace_path, list(dependency_task_ids), ("applied", "integrated"))

    def apply_cycle_changes(self, workspace_path: Path, mission_id: str, cycle: int) -> None:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT task_id FROM development_task_workspaces WHERE mission_id=? AND cycle=? "
                "AND status IN ('ready','integrated') ORDER BY task_id",
                (mission_id, cycle),
            ).fetchall()
        self._apply_changes(workspace_path, [row["task_id"] for row in rows], ("applied", "integrated"))

    def recover_expired_leases(self, now: float | None = None) -> int:
        moment = time.time() if now is None else now
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "UPDATE development_task_workspaces SET status='orphaned',owner_worker_id='',"
                "lease_until=NULL,updated_at=? "
                "WHERE status='active' AND lease_until IS NOT NULL AND lease_until<=?",
                (time.time(), moment),
            )
            return cursor.rowcount

    def _ready_task_ids(self, mission_id: str, cycle: int) -> list[str]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT task_id FROM development_task_workspaces WHERE mission_id=? AND cycle<=? "
                "AND status='ready' AND integration_status IN ('pending','verified') ORDER BY cycle,task_id",
                (mission_id, cycle),
            ).fetchall()
        return [row["task_id"] for row in rows]

    def _changes_for_tasks(self, task_ids: list[str]) -> list[sqlite3.Row]:
        if not task_ids:
            return []
        markers = ",".join("?" for _ in task_ids)
        with closing(self._connect()) as db:
            return db.execute(
                f"SELECT * FROM development_task_workspace_changes WHERE task_id IN ({markers}) "
                "AND status IN ('applied','integrated') ORDER BY relative_path,task_id",
                tuple(task_ids),
            ).fetchall()

    def _overlap_conflict(self, changes: list[sqlite3.Row]) -> str:
        by_path: dict[str, list[str]] = {}
        for row in changes:
            by_path.setdefault(row["relative_path"], []).append(row["task_id"])
        overlaps = {
            path: sorted(set(task_ids))
            for path, task_ids in by_path.items()
            if len(set(task_ids)) > 1
        }
        if not overlaps:
            return ""
        detail = "; ".join(f"{path}: {', '.join(task_ids)}" for path, task_ids in sorted(overlaps.items()))
        return "Multiple tasks changed the same file; integration is blocked: " + detail

    def build_candidate(self, mission_id: str, cycle: int, source_root: str | Path | None = None) -> dict:
        candidate_key = f"{mission_id}:{cycle}"
        task_ids = self._ready_task_ids(mission_id, cycle)
        changes = self._changes_for_tasks(task_ids)
        overlap = self._overlap_conflict(changes)
        if source_root is not None:
            source = Path(source_root).resolve()
        else:
            with closing(self._connect()) as db:
                row = db.execute(
                    "SELECT source_root FROM development_task_workspaces WHERE mission_id=? ORDER BY cycle DESC LIMIT 1",
                    (mission_id,),
                ).fetchone()
            source = Path(row["source_root"]).resolve() if row else Path.cwd().resolve()
        if not source.is_dir() or source.is_symlink():
            raise TaskWorkspaceError("Candidate source root must be a real directory.")
        path = self._candidate_path(candidate_key)
        now = time.time()
        digest_source = json.dumps(
            [[row["task_id"], row["relative_path"], row["new_sha256"]] for row in changes],
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(digest_source).hexdigest()
        reusable = False
        with closing(self._connect()) as db, db:
            existing = db.execute(
                "SELECT status,conflict,digest,workspace_path FROM development_task_workspace_candidates "
                "WHERE candidate_key=?",
                (candidate_key,),
            ).fetchone()
            if (
                existing
                and existing["digest"] == digest
                and existing["status"] in {"verified", "integrated"}
                and Path(existing["workspace_path"]).is_dir()
            ):
                return {
                    "key": candidate_key,
                    "path": existing["workspace_path"],
                    "status": existing["status"],
                    "conflict": existing["conflict"],
                    "digest": digest,
                    "changes": len(changes),
                }
            reusable = bool(existing and existing["digest"] == digest and Path(existing["workspace_path"]).is_dir())
            db.execute(
                "INSERT INTO development_task_workspace_candidates "
                "(candidate_key,mission_id,cycle,source_root,workspace_path,digest,status,conflict,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(candidate_key) DO UPDATE SET "
                "source_root=excluded.source_root,workspace_path=excluded.workspace_path,digest=excluded.digest,"
                "status=excluded.status,conflict=excluded.conflict,updated_at=excluded.updated_at",
                (
                    candidate_key, mission_id, cycle, str(source), str(path), digest,
                    "blocked" if overlap else "building", overlap, now, now,
                ),
            )
        if not reusable:
            self._copy_source(source, path)
            self._apply_changes(path, task_ids, ("applied", "integrated"))
        return {
            "key": candidate_key,
            "path": str(path),
            "status": "blocked" if overlap else "building",
            "conflict": overlap,
            "digest": digest,
            "changes": len(changes),
        }

    def _candidate_digest(self, candidate_key: str) -> str:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT digest FROM development_task_workspace_candidates WHERE candidate_key=?",
                (candidate_key,),
            ).fetchone()
        return row["digest"] if row else ""

    def mark_candidate_status(self, mission_id: str, cycle: int, status: str) -> None:
        if status not in CANDIDATE_STATUSES:
            raise TaskWorkspaceError("Unsupported candidate status.")
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "UPDATE development_task_workspace_candidates SET status=?,updated_at=? "
                "WHERE candidate_key=?",
                (status, time.time(), f"{mission_id}:{cycle}"),
            )
            if cursor.rowcount != 1:
                raise TaskWorkspaceError("Candidate workspace was not found.")

    def integrate_latest_candidate(self, mission_id: str) -> dict:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT cycle FROM development_task_workspace_candidates WHERE mission_id=? "
                "AND status='verified' ORDER BY cycle DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
        if row is None:
            return {"ok": True, "missing": True, "changes": 0, "conflicts": []}
        return self.integrate_candidate(mission_id, row["cycle"])

    def integrate_candidate(self, mission_id: str, cycle: int) -> dict:
        candidate_key = f"{mission_id}:{cycle}"
        with closing(self._connect()) as db:
            candidate = db.execute(
                "SELECT * FROM development_task_workspace_candidates WHERE candidate_key=?",
                (candidate_key,),
            ).fetchone()
        if candidate is None:
            return {"ok": True, "missing": True, "changes": 0, "conflicts": []}
        if candidate["status"] == "integrated":
            return {"ok": True, "missing": False, "changes": 0, "conflicts": []}
        source = Path(candidate["source_root"]).resolve()
        if not source.is_dir() or source.is_symlink():
            raise TaskWorkspaceError("Candidate source root is no longer available.")
        task_ids = self._ready_task_ids(mission_id, cycle)
        changes = self._changes_for_tasks(task_ids)
        overlap = self._overlap_conflict(changes)
        conflicts = [overlap] if overlap else []
        for row in changes:
            rel = _validate_relative(row["relative_path"])
            target = _safe_target(source, rel)
            if _file_digest(target) != row["base_sha256"]:
                conflicts.append(f"{row['relative_path']} changed in the shared source since isolation.")
        if conflicts:
            now = time.time()
            with closing(self._connect()) as db, db:
                db.execute(
                    "UPDATE development_task_workspace_candidates SET status='blocked',conflict=?,updated_at=? "
                    "WHERE candidate_key=?",
                    (" | ".join(conflicts)[:4000], now, candidate_key),
                )
                db.execute(
                    "UPDATE development_task_workspaces SET integration_status='conflict',updated_at=? "
                    "WHERE mission_id=? AND cycle=? AND status IN ('ready','integrated')",
                    (now, mission_id, cycle),
                )
                db.execute(
                    "UPDATE development_task_workspace_changes SET status='conflict',updated_at=? "
                    "WHERE task_id IN (%s) AND status IN ('applied','integrated')" % ",".join("?" for _ in task_ids),
                    (now, *task_ids),
                )
            return {"ok": False, "missing": False, "changes": len(changes), "conflicts": conflicts}
        for row in changes:
            rel = _validate_relative(row["relative_path"])
            target = _safe_target(source, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            with _locked_path(target, owner={"task_id": "candidate-integration"}):
                target = _safe_target(source, rel)
                if _file_digest(target) != row["base_sha256"]:
                    raise TaskWorkspaceError("Candidate source changed during integration; no further files were written.")
                _atomic_replace_text(target, row["content"])
        now = time.time()
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE development_task_workspace_candidates SET status='integrated',conflict='',updated_at=? "
                "WHERE candidate_key=?",
                (now, candidate_key),
            )
            db.execute(
                "UPDATE development_task_workspaces SET status='integrated',integration_status='integrated',updated_at=? "
                "WHERE mission_id=? AND cycle=? AND status IN ('ready','integrated')",
                (now, mission_id, cycle),
            )
            if task_ids:
                db.execute(
                    "UPDATE development_task_workspace_changes SET status='integrated',updated_at=? "
                    "WHERE task_id IN (%s)" % ",".join("?" for _ in task_ids),
                    (now, *task_ids),
                )
        return {"ok": True, "missing": False, "changes": len(changes), "conflicts": []}

    def workspace_status(self, task_id: str) -> dict | None:
        row = self._row(task_id)
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "status": row["status"],
            "integration_status": row["integration_status"],
            "owner_worker_id": row["owner_worker_id"],
            "workspace_path": row["workspace_path"],
        }
