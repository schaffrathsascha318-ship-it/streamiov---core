"""Durable project-wide supervisor for consecutive Streamiov development missions.

The supervisor reuses the existing mission engine and SQLite database. It keeps
one project goal, resumes an active mission after restart, and starts a distinct
next mission only after the mission engine reports its independent completion
gate as satisfied.
"""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from ai.runtime.continuous_engine import (
    ContinuousDevelopmentEngine,
    MissionEngineError,
    MissionSnapshot,
)

DEFAULT_SUPERVISOR_KEY = "streamiov-project"
SUPERVISOR_LEASE_SECONDS = 30
SUPERVISOR_HEARTBEAT_SECONDS = 5
MAX_PROGRESS_CHARS = 12000


class ProjectSupervisorError(RuntimeError):
    """Raised when project supervision cannot safely proceed."""


class ProjectSupervisor:
    """Keep one durable project goal moving across independently verified missions."""

    def __init__(
        self,
        engine: ContinuousDevelopmentEngine,
        database_path: str | Path,
        *,
        supervisor_key: str = DEFAULT_SUPERVISOR_KEY,
        lease_seconds: int = SUPERVISOR_LEASE_SECONDS,
        heartbeat_seconds: float = SUPERVISOR_HEARTBEAT_SECONDS,
    ) -> None:
        if not supervisor_key or len(supervisor_key) > 128:
            raise ValueError("supervisor_key must contain 1–128 characters")
        if lease_seconds < 10 or heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("invalid supervisor lease or heartbeat interval")
        self.engine = engine
        self.database_path = str(database_path)
        path = Path(self.database_path)
        if self.database_path == ":memory:" or path.is_symlink():
            raise ProjectSupervisorError("Supervisor requires a durable, non-symlink SQLite database.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.supervisor_key = supervisor_key
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.owner_id = uuid.uuid4().hex
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with closing(self._connect()) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS development_supervisors (
                    supervisor_key TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    active_mission_id TEXT,
                    progress TEXT NOT NULL DEFAULT '',
                    completed_missions INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    updated_at REAL NOT NULL
                )
            """)

    def configure(self, goal: str) -> None:
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 8000:
            raise ProjectSupervisorError("Project goal must contain 1–8000 characters.")
        now = time.time()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT goal,active_mission_id,lease_owner,lease_until FROM development_supervisors WHERE supervisor_key=?",
                (self.supervisor_key,),
            ).fetchone()
            if row and row["goal"] != goal.strip():
                db.rollback()
                raise ProjectSupervisorError(
                    "The persistent project goal cannot be replaced in place; use the existing goal to resume."
                )
            if row and row["lease_until"] and row["lease_until"] > now and row["lease_owner"] != self.owner_id:
                db.rollback()
                raise ProjectSupervisorError("Another project supervisor currently holds the lease.")
            db.execute("""
                INSERT INTO development_supervisors(supervisor_key,goal,updated_at)
                VALUES(?,?,?)
                ON CONFLICT(supervisor_key) DO UPDATE SET goal=excluded.goal,updated_at=excluded.updated_at
            """, (self.supervisor_key, goal.strip(), now))
            db.commit()

    def configure_if_missing(
        self, goal: str, *, active_mission_id: str | None = None
    ) -> bool:
        """Create the durable goal once without overwriting restored state."""
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 8000:
            raise ProjectSupervisorError("Project goal must contain 1–8000 characters.")
        if active_mission_id is not None and (
            not isinstance(active_mission_id, str) or not active_mission_id.strip()
            or len(active_mission_id) > 96
        ):
            raise ProjectSupervisorError("Initial mission ID must contain 1–96 characters.")
        now = time.time()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT supervisor_key FROM development_supervisors WHERE supervisor_key=?",
                (self.supervisor_key,),
            ).fetchone()
            if row is not None:
                db.commit()
                return False
            db.execute(
                "INSERT INTO development_supervisors(supervisor_key,goal,active_mission_id,updated_at) VALUES(?,?,?,?)",
                (self.supervisor_key, goal.strip(), active_mission_id, now),
            )
            db.commit()
            return True

    def _acquire_lease(self) -> None:
        now = time.time()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT lease_owner,lease_until FROM development_supervisors WHERE supervisor_key=?",
                (self.supervisor_key,),
            ).fetchone()
            if row is None:
                db.rollback()
                raise ProjectSupervisorError("Configure a project goal before starting the supervisor.")
            if row["lease_until"] and row["lease_until"] > now and row["lease_owner"] != self.owner_id:
                db.rollback()
                raise ProjectSupervisorError("A different supervisor process is already running.")
            db.execute("""
                UPDATE development_supervisors
                SET lease_owner=?,lease_until=?,updated_at=?
                WHERE supervisor_key=?
            """, (self.owner_id, now + self.lease_seconds, now, self.supervisor_key))
            db.commit()

    def _renew_lease(self) -> bool:
        now = time.time()
        with closing(self._connect()) as db:
            cursor = db.execute("""
                UPDATE development_supervisors
                SET lease_until=?,updated_at=?
                WHERE supervisor_key=? AND lease_owner=?
            """, (now + self.lease_seconds, now, self.supervisor_key, self.owner_id))
            return cursor.rowcount == 1

    def _release_lease(self) -> None:
        with closing(self._connect()) as db:
            db.execute("""
                UPDATE development_supervisors
                SET lease_owner='',lease_until=NULL,updated_at=?
                WHERE supervisor_key=? AND lease_owner=?
            """, (time.time(), self.supervisor_key, self.owner_id))

    def _heartbeat(self, stop_event: threading.Event, lost_lease: threading.Event) -> None:
        while not stop_event.wait(self.heartbeat_seconds):
            try:
                if not self._renew_lease():
                    lost_lease.set()
                    stop_event.set()
                    return
            except sqlite3.Error:
                lost_lease.set()
                stop_event.set()
                return

    def _state(self) -> sqlite3.Row:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM development_supervisors WHERE supervisor_key=?",
                (self.supervisor_key,),
            ).fetchone()
        if row is None:
            raise ProjectSupervisorError("Project supervisor state is missing.")
        return row

    def _next_mission(self, row: sqlite3.Row) -> str:
        mission_id = row["active_mission_id"]
        if not mission_id:
            mission_id = uuid.uuid4().hex
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                cursor = db.execute("""
                    UPDATE development_supervisors
                    SET active_mission_id=?,updated_at=?
                    WHERE supervisor_key=? AND lease_owner=? AND active_mission_id IS NULL
                """, (mission_id, time.time(), self.supervisor_key, self.owner_id))
                if cursor.rowcount != 1:
                    db.rollback()
                    raise ProjectSupervisorError("Supervisor lease or mission state changed unexpectedly.")
                db.commit()
            row = self._state()

        try:
            self.engine.get_mission(mission_id)
            return mission_id
        except MissionEngineError:
            goal = row["goal"].strip()
            progress = (row["progress"] or "").strip()
            # The original intake goal may already be close to the engine's
            # 8,000-character limit. Bound both carried sections before adding
            # supervisor instructions, so a fresh mission can always be created.
            truncation_marker = "\n\n[Middle omitted; see the durable project goal/progress record.]\n\n"

            def bounded(value: str, limit: int, *, keep_tail: bool = False) -> str:
                if len(value) <= limit:
                    return value
                available = max(0, limit - len(truncation_marker))
                if keep_tail:
                    return truncation_marker + value[-available:] if available else value[-limit:]
                head = (available * 2) // 3
                tail = available - head
                return value[:head] + truncation_marker + (value[-tail:] if tail else "")

            goal = bounded(goal, 5000)
            progress = bounded(
                progress or "No project missions have been verified yet.",
                2000,
                keep_tail=True,
            )
            mission_goal = (
                f"PROJECT-WIDE STREAMIOV GOAL:\n{goal}\n\n"
                "Continue the project from its verified state. Identify the next highest-priority "
                "unfinished deliverable from the repository and the cumulative progress below. "
                "Do not repeat completed work; repair blockers before starting unrelated work. "
                "Completion requires the mission engine's independent testing-specialist verification.\n\n"
                f"VERIFIED PROJECT PROGRESS:\n{progress}"
            )
            return self.engine.create_mission(mission_goal, mission_id=mission_id)

    def run(
        self,
        stop_event: threading.Event,
        *,
        poll_seconds: float = 5.0,
        emit: Callable[[str], None] = print,
    ) -> MissionSnapshot | None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._acquire_lease()
        heartbeat_stop = threading.Event()
        lost_lease = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat, args=(heartbeat_stop, lost_lease),
            name="streamiov-project-supervisor-heartbeat", daemon=True,
        )
        heartbeat.start()
        last_snapshot = None
        try:
            emit(json.dumps({"event": "supervisor_started", "supervisor_key": self.supervisor_key}))
            while not stop_event.is_set() and not lost_lease.is_set():
                row = self._state()
                mission_id = self._next_mission(row)
                emit(json.dumps({
                    "event": "supervisor_mission_started",
                    "mission_id": mission_id,
                    "completed_missions": row["completed_missions"],
                }, ensure_ascii=False))
                retry_wait = [0.0]

                def capture(message: str) -> None:
                    emit(message)
                    try:
                        event = json.loads(message)
                    except (TypeError, json.JSONDecodeError):
                        return
                    if (
                        event.get("event") in {
                            "mission_waiting_for_retry",
                            "mission_waiting_for_planning_retry",
                            "mission_progress_blocked",
                        }
                        and event.get("supervisor_wait") is True
                    ):
                        retry_wait[0] = max(retry_wait[0], float(event.get("retry_after_seconds", 0)))

                try:
                    last_snapshot = self.engine.run(
                        mission_id, stop_event, poll_seconds=poll_seconds, emit=capture,
                        worker_id=f"project-supervisor-{self.owner_id}",
                    )
                except Exception as exc:
                    emit(json.dumps({
                        "event": "mission_engine_recovered", "mission_id": mission_id,
                        "error": f"{type(exc).__name__}: {str(exc)[:1000]}",
                    }, ensure_ascii=False))
                    last_snapshot = self.engine.get_mission(mission_id)
                if lost_lease.is_set():
                    raise ProjectSupervisorError("Supervisor lease was lost; stopping to prevent duplicate work.")
                if last_snapshot.status == "completed":
                    with closing(self._connect()) as db:
                        db.execute("BEGIN IMMEDIATE")
                        previous_progress = row["progress"] or ""
                        milestone = (
                            f"Mission {mission_id} (verified): "
                            f"{last_snapshot.summary or 'Independent completion gate passed.'}"
                        )
                        cumulative_progress = (
                            f"{previous_progress}\n\n{milestone}".strip()
                            if previous_progress else milestone
                        )[-MAX_PROGRESS_CHARS:]
                        cursor = db.execute("""
                            UPDATE development_supervisors
                            SET progress=?,active_mission_id=NULL,
                                completed_missions=completed_missions+1,updated_at=?
                            WHERE supervisor_key=? AND lease_owner=? AND active_mission_id=?
                        """, (
                            cumulative_progress,
                            time.time(), self.supervisor_key, self.owner_id, mission_id,
                        ))
                        if cursor.rowcount != 1:
                            db.rollback()
                            raise ProjectSupervisorError("Could not persist verified mission completion.")
                        db.commit()
                    emit(json.dumps({
                        "event": "supervisor_mission_verified",
                        "mission_id": mission_id,
                        "next": "starting_next_mission",
                    }, ensure_ascii=False))
                    continue
                if stop_event.is_set():
                    break
                delay = retry_wait[0] if retry_wait[0] > 0 else poll_seconds
                stop_event.wait(delay)
            return last_snapshot
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=self.heartbeat_seconds + 1)
            self._release_lease()
