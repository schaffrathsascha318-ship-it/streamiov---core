"""Durable read-only local AI task records for the StreamioV host."""
from __future__ import annotations

from contextlib import closing, contextmanager
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


TASK_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
REQUEST_MIN = 1
REQUEST_MAX = 2000
ANSWER_MAX = 4000
TASK_STATUSES = {"queued", "running", "completed", "failed"}


class AITaskError(ValueError):
    """Safe-to-return AI task validation or state error."""


def validate_request(value: object) -> str:
    if not isinstance(value, str):
        raise AITaskError("Request text must be a string.")
    text = value.strip()
    if not REQUEST_MIN <= len(text) <= REQUEST_MAX:
        raise AITaskError(f"Request text must be between {REQUEST_MIN} and {REQUEST_MAX} characters.")
    if "\x00" in text:
        raise AITaskError("Request text contains invalid characters.")
    return text


class AITaskStore:
    """SQLite-backed task history for the fail-closed local AI endpoint."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.database = self.data_dir / "ai_tasks.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _transaction(self):
        with closing(self._connect()) as db:
            with db:
                yield db

    def _initialize(self) -> None:
        with self._transaction() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ai_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    answer TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS ai_tasks_owner_created ON ai_tasks(user_id, created_at);
            """)
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict:
        return {
            "id": row["task_id"],
            "user_id": row["user_id"],
            "request": row["request"],
            "status": row["status"],
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
            "answer": row["answer"],
            "provider": row["provider"],
            "model": row["model"],
            "error": row["error"],
        }

    def create(self, user_id: object, request: object) -> dict:
        if not isinstance(user_id, str) or not user_id:
            raise AITaskError("Anmeldung erforderlich.")
        clean_request = validate_request(request)
        task_id = uuid.uuid4().hex
        now = int(time.time())
        with self._transaction() as db:
            db.execute("""
                INSERT INTO ai_tasks(task_id, user_id, request, status, created_at, updated_at)
                VALUES(?,?,?,'queued',?,?)
            """, (task_id, user_id, clean_request, now, now))
        return {
            "id": task_id,
            "user_id": user_id,
            "request": clean_request,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "answer": "",
            "provider": "",
            "model": "",
            "error": "",
        }

    def get(self, task_id: object, user_id: object) -> dict | None:
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            return None
        if not isinstance(user_id, str) or not user_id:
            return None
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM ai_tasks WHERE task_id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
        return self._payload(row) if row is not None else None

    def list(self, user_id: object, *, limit: int = 50) -> list[dict]:
        if not isinstance(user_id, str) or not user_id:
            raise AITaskError("Anmeldung erforderlich.")
        limit = max(1, min(int(limit), 100))
        with closing(self._connect()) as db:
            rows = db.execute("""
                SELECT * FROM ai_tasks WHERE user_id = ?
                 ORDER BY created_at DESC, task_id DESC LIMIT ?
            """, (user_id, limit)).fetchall()
        return [self._payload(row) for row in rows]

    def mark_running(self, task_id: object) -> bool:
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            return False
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE ai_tasks SET status = 'running', updated_at = ? "
                "WHERE task_id = ? AND status = 'queued'",
                (int(time.time()), task_id),
            )
            return cursor.rowcount == 1

    def complete(self, task_id: object, *, answer: object, provider: object, model: object) -> bool:
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            return False
        if not isinstance(answer, str) or not answer.strip():
            return False
        with self._transaction() as db:
            cursor = db.execute("""
                UPDATE ai_tasks
                   SET status = 'completed', updated_at = ?, answer = ?,
                       provider = ?, model = ?, error = ''
                 WHERE task_id = ? AND status IN ('queued', 'running')
            """, (int(time.time()), answer[:ANSWER_MAX], str(provider or '')[:80],
                  str(model or '')[:80], task_id))
            return cursor.rowcount == 1

    def fail(self, task_id: object, error: object) -> bool:
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            return False
        with self._transaction() as db:
            cursor = db.execute("""
                UPDATE ai_tasks
                   SET status = 'failed', updated_at = ?, error = ?, answer = ''
                 WHERE task_id = ? AND status IN ('queued', 'running')
            """, (int(time.time()), str(error)[:300], task_id))
            return cursor.rowcount == 1
