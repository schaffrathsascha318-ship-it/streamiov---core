"""SQLite-backed durable queue for bounded STREAMIOV specialist tasks.

This module provides persistence and lease-based claiming. It is not itself a
background daemon; callers must run workers and supply the existing safe agent.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ai.core.orchestrator import SpecialistTask, TaskOrchestrator, TaskPlanError
from ai.specialists.registry import get_specialist


QueueStatus = Literal["queued", "running", "succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class QueuedTask:
    task_id: str
    specialist: str
    prompt: str
    depends_on: tuple[str, ...]
    status: QueueStatus
    attempts: int
    max_attempts: int
    result: str = ""
    error: str = ""
    worker_id: str = ""


class TaskQueueError(RuntimeError):
    pass


class SpecialistTaskQueue:
    def __init__(self, database_path: str | Path, *, max_tasks_per_plan: int = 32) -> None:
        raw_path = str(database_path)
        if raw_path != ":memory:":
            path = Path(database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                raise TaskQueueError("Queue database must not be a symlink.")
            self.database_path = str(path)
        else:
            self.database_path = raw_path
        self.max_tasks_per_plan = max_tasks_per_plan
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            if connection.in_transaction:
                connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS specialist_tasks (
                    task_id TEXT PRIMARY KEY,
                    queue_order INTEGER NOT NULL DEFAULT 0,
                    specialist TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','skipped')),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 5),
                    result TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    worker_id TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(specialist_tasks)")}
            if "queue_order" not in columns:
                connection.execute("ALTER TABLE specialist_tasks ADD COLUMN queue_order INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_specialist_tasks_claim "
                "ON specialist_tasks(status, queue_order, task_id)"
            )

    def enqueue_plan(
        self,
        tasks: list[SpecialistTask] | tuple[SpecialistTask, ...],
        *,
        max_attempts: int = 1,
    ) -> list[str]:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 5:
            raise TaskQueueError("max_attempts must be between 1 and 5.")
        plan = tuple(tasks)
        # Reuse the exact same preflight validation as the in-process orchestrator.
        try:
            ordered = TaskOrchestrator(lambda _role: None, max_tasks=self.max_tasks_per_plan)._validate_and_order(plan)
        except TaskPlanError as exc:
            raise TaskQueueError(str(exc)) from exc
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            first_order = connection.execute("SELECT COALESCE(MAX(queue_order), -1) + 1 FROM specialist_tasks").fetchone()[0]
            for index, task in enumerate(ordered):
                connection.execute(
                    """
                    INSERT INTO specialist_tasks
                    (task_id, queue_order, specialist, prompt, depends_on, status, attempts, max_attempts, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?)
                    """,
                    (task.task_id, first_order + index, task.specialist, task.prompt, json.dumps(task.depends_on), max_attempts, now, now),
                )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise TaskQueueError("Task plan could not be enqueued; an ID may already exist.") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return [task.task_id for task in ordered]

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> QueuedTask:
        return QueuedTask(
            task_id=row["task_id"],
            specialist=row["specialist"],
            prompt=row["prompt"],
            depends_on=tuple(json.loads(row["depends_on"])),
            status=row["status"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            result=row["result"],
            error=row["error"],
            worker_id=row["worker_id"],
        )

    def claim_next(self, worker_id: str, *, lease_seconds: int = 300) -> QueuedTask | None:
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
            raise TaskQueueError("worker_id must contain 1–128 characters.")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 10 <= lease_seconds <= 3600:
            raise TaskQueueError("lease_seconds must be between 10 and 3600.")
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            # Recover abandoned leases. A task that exhausted its retry budget fails closed.
            connection.execute(
                """
                UPDATE specialist_tasks
                SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                    worker_id = '', lease_until = NULL,
                    error = CASE WHEN attempts < max_attempts THEN error ELSE 'Worker lease expired; retry budget exhausted.' END,
                    updated_at = ?
                WHERE status = 'running' AND lease_until <= ?
                """,
                (now, now),
            )
            # Dependants of terminal failures are skipped, never run with missing prerequisites.
            rows = connection.execute(
                "SELECT task_id, depends_on FROM specialist_tasks WHERE status = 'queued'"
            ).fetchall()
            for row in rows:
                dependencies = json.loads(row["depends_on"])
                if not dependencies:
                    continue
                placeholders = ",".join("?" for _ in dependencies)
                states = connection.execute(
                    f"SELECT task_id, status FROM specialist_tasks WHERE task_id IN ({placeholders})",
                    dependencies,
                ).fetchall()
                state_by_id = {item["task_id"]: item["status"] for item in states}
                if any(state_by_id.get(dep) in {"failed", "skipped"} for dep in dependencies):
                    connection.execute(
                        "UPDATE specialist_tasks SET status='skipped', error='A prerequisite task did not succeed.', updated_at=? WHERE task_id=? AND status='queued'",
                        (now, row["task_id"]),
                    )
            candidates = connection.execute(
                "SELECT * FROM specialist_tasks WHERE status='queued' ORDER BY queue_order, task_id"
            ).fetchall()
            selected = None
            for row in candidates:
                dependencies = json.loads(row["depends_on"])
                if dependencies:
                    placeholders = ",".join("?" for _ in dependencies)
                    states = connection.execute(
                        f"SELECT status FROM specialist_tasks WHERE task_id IN ({placeholders})",
                        dependencies,
                    ).fetchall()
                    if len(states) != len(dependencies) or any(item["status"] != "succeeded" for item in states):
                        continue
                selected = row
                break
            if selected is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE specialist_tasks
                SET status='running', attempts=attempts+1, worker_id=?, lease_until=?, updated_at=?
                WHERE task_id=? AND status='queued'
                """,
                (worker_id.strip(), now + lease_seconds, now, selected["task_id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM specialist_tasks WHERE task_id=?",
                (selected["task_id"],),
            ).fetchone()
            connection.commit()
            return self._row_to_task(claimed)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat(self, task_id: str, worker_id: str, *, lease_seconds: int = 300) -> None:
        if not 10 <= lease_seconds <= 3600:
            raise TaskQueueError("lease_seconds must be between 10 and 3600.")
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE specialist_tasks SET lease_until=?, updated_at=? WHERE task_id=? AND worker_id=? AND status='running'",
                (now + lease_seconds, now, task_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise TaskQueueError("Task is not running under this worker lease.")

    def complete(self, task_id: str, worker_id: str, result: str) -> None:
        if not isinstance(result, str) or len(result) > 12000:
            raise TaskQueueError("Task result must be text no longer than 12,000 characters.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE specialist_tasks
                SET status='succeeded', result=?, error='', worker_id='', lease_until=NULL, updated_at=?
                WHERE task_id=? AND worker_id=? AND status='running' AND lease_until>?
                """,
                (result, time.time(), task_id, worker_id, time.time()),
            )
            if cursor.rowcount != 1:
                raise TaskQueueError("Task is not running under this worker lease.")

    def fail(self, task_id: str, worker_id: str, error: str) -> QueueStatus:
        safe_error = str(error)[:1000]
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempts, max_attempts FROM specialist_tasks WHERE task_id=? AND worker_id=? AND status='running'",
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                raise TaskQueueError("Task is not running under this worker lease.")
            status: QueueStatus = "queued" if row["attempts"] < row["max_attempts"] else "failed"
            connection.execute(
                """
                UPDATE specialist_tasks
                SET status=?, error=?, worker_id='', lease_until=NULL, updated_at=?
                WHERE task_id=? AND worker_id=? AND status='running'
                """,
                (status, safe_error, time.time(), task_id, worker_id),
            )
            return status

    def get(self, task_id: str) -> QueuedTask | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM specialist_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self) -> list[QueuedTask]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM specialist_tasks ORDER BY created_at, task_id").fetchall()
        return [self._row_to_task(row) for row in rows]


@dataclass(frozen=True)
class WorkerExecution:
    task_id: str
    status: QueueStatus
    result: str = ""
    error: str = ""


class SpecialistWorker:
    """Run at most one claimed task using the existing role-scoped agent factory."""

    def __init__(self, queue: SpecialistTaskQueue, worker_id: str, agent_factory, *, lease_seconds: int = 300) -> None:
        if not callable(agent_factory):
            raise TypeError("agent_factory must be callable")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id is required")
        self.queue = queue
        self.worker_id = worker_id
        self.agent_factory = agent_factory
        self.lease_seconds = lease_seconds

    def run_once(self) -> WorkerExecution | None:
        task = self.queue.claim_next(self.worker_id, lease_seconds=self.lease_seconds)
        if task is None:
            return None
        try:
            result = self.agent_factory(task.specialist).run(task.prompt)
            if not isinstance(result, str):
                raise TypeError("Specialist agent returned a non-text result.")
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
            status = self.queue.fail(task.task_id, self.worker_id, error)
            return WorkerExecution(task.task_id, status, error=error)
        self.queue.complete(task.task_id, self.worker_id, result)
        return WorkerExecution(task.task_id, "succeeded", result=result)
