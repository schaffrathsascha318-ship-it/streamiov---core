"""Local community forum storage for the StreamioV host.

The forum is a separate SQLite database. Reads are public; every write needs an
authenticated host session. This module contains no HTTP handling so it can be
tested and moderated from the operator CLI.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from host.auth import User


THREAD_TITLE_MIN = 3
THREAD_TITLE_MAX = 140
THREAD_BODY_MAX = 10_000
REPLY_BODY_MAX = 5_000
THREAD_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
REPLY_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ForumError(ValueError):
    """Safe-to-return forum validation or state error."""


@dataclass(frozen=True)
class ForumThread:
    thread_id: str
    title: str
    body: str
    author_user_id: str
    author_name: str
    created_at: int
    locked: bool
    reply_count: int
    last_activity: int


def _clean_text(value: object, *, field: str, minimum: int, maximum: int,
                single_line: bool = False) -> str:
    if not isinstance(value, str):
        raise ForumError(f"{field} muss Text sein.")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) < minimum:
        raise ForumError(f"{field} muss mindestens {minimum} Zeichen enthalten.")
    if len(text) > maximum:
        raise ForumError(f"{field} darf höchstens {maximum} Zeichen enthalten.")
    if "\x00" in text:
        raise ForumError(f"{field} enthält ungültige Zeichen.")
    for character in text:
        code = ord(character)
        if code < 32 and character not in ("\n", "\t"):
            raise ForumError(f"{field} enthält ungültige Steuerzeichen.")
        if single_line and character in ("\n", "\t"):
            raise ForumError(f"{field} muss einzeilig sein.")
    return text


def validate_title(value: object) -> str:
    return _clean_text(value, field="Titel", minimum=THREAD_TITLE_MIN,
                       maximum=THREAD_TITLE_MAX, single_line=True)


def validate_thread_body(value: object) -> str:
    return _clean_text(value, field="Beitrag", minimum=1, maximum=THREAD_BODY_MAX)


def validate_reply_body(value: object) -> str:
    return _clean_text(value, field="Antwort", minimum=1, maximum=REPLY_BODY_MAX)


class ForumStore:
    """SQLite-backed forum with soft deletes and operator lock support."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.database = self.data_dir / "forum.sqlite3"
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
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    author_user_id TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS replies (
                    reply_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    author_user_id TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS threads_created ON threads(deleted, created_at);
                CREATE INDEX IF NOT EXISTS replies_thread ON replies(thread_id, deleted, created_at);
            """)
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @staticmethod
    def _thread_payload(row: sqlite3.Row) -> dict:
        return {
            "id": row["thread_id"],
            "title": row["title"],
            "body": row["body"],
            "author": row["author_name"],
            "created_at": int(row["created_at"]),
            "locked": bool(row["locked"]),
            "reply_count": int(row["reply_count"]),
            "last_activity": int(row["last_activity"]),
        }

    @staticmethod
    def _reply_payload(row: sqlite3.Row) -> dict:
        return {
            "id": row["reply_id"],
            "thread_id": row["thread_id"],
            "body": row["body"],
            "author": row["author_name"],
            "created_at": int(row["created_at"]),
        }

    def list_threads(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        with closing(self._connect()) as db:
            rows = db.execute("""
                SELECT t.thread_id, t.title, t.body, t.author_name, t.created_at,
                       t.locked,
                       (SELECT COUNT(*) FROM replies r
                         WHERE r.thread_id = t.thread_id AND r.deleted = 0) AS reply_count,
                       COALESCE((SELECT MAX(r.created_at) FROM replies r
                         WHERE r.thread_id = t.thread_id AND r.deleted = 0), t.created_at) AS last_activity
                  FROM threads t
                 WHERE t.deleted = 0
                 ORDER BY t.created_at DESC
                 LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
        return [self._thread_payload(row) for row in rows]

    def get_thread(self, thread_id: object) -> dict | None:
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            return None
        with closing(self._connect()) as db:
            row = db.execute("""
                SELECT t.thread_id, t.title, t.body, t.author_name, t.created_at,
                       t.locked,
                       (SELECT COUNT(*) FROM replies r
                         WHERE r.thread_id = t.thread_id AND r.deleted = 0) AS reply_count,
                       COALESCE((SELECT MAX(r.created_at) FROM replies r
                         WHERE r.thread_id = t.thread_id AND r.deleted = 0), t.created_at) AS last_activity
                  FROM threads t
                 WHERE t.thread_id = ? AND t.deleted = 0
            """, (thread_id,)).fetchone()
            if row is None:
                return None
            replies = db.execute("""
                SELECT reply_id, thread_id, body, author_name, created_at
                  FROM replies
                 WHERE thread_id = ? AND deleted = 0
                 ORDER BY created_at ASC
            """, (thread_id,)).fetchall()
        payload = self._thread_payload(row)
        payload["replies"] = [self._reply_payload(reply) for reply in replies]
        return payload

    def create_thread(self, user: User, title: object, body: object) -> dict:
        if not isinstance(user, User):
            raise ForumError("Anmeldung erforderlich.")
        clean_title = validate_title(title)
        clean_body = validate_thread_body(body)
        thread_id = uuid.uuid4().hex
        now = int(time.time())
        with self._transaction() as db:
            db.execute("""
                INSERT INTO threads(thread_id, title, body, author_user_id, author_name, created_at)
                VALUES(?,?,?,?,?,?)
            """, (thread_id, clean_title, clean_body, user.user_id, user.username, now))
        return self.get_thread(thread_id) or {}

    def create_reply(self, user: User, thread_id: object, body: object) -> dict:
        if not isinstance(user, User):
            raise ForumError("Anmeldung erforderlich.")
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            raise ForumError("Thema wurde nicht gefunden.")
        clean_body = validate_reply_body(body)
        reply_id = uuid.uuid4().hex
        now = int(time.time())
        with self._transaction() as db:
            thread = db.execute(
                "SELECT locked FROM threads WHERE thread_id = ? AND deleted = 0", (thread_id,)
            ).fetchone()
            if thread is None:
                raise ForumError("Thema wurde nicht gefunden.")
            if thread["locked"]:
                raise ForumError("Dieses Thema ist gesperrt.")
            db.execute("""
                INSERT INTO replies(reply_id, thread_id, body, author_user_id, author_name, created_at)
                VALUES(?,?,?,?,?,?)
            """, (reply_id, thread_id, clean_body, user.user_id, user.username, now))
            row = db.execute("""
                SELECT reply_id, thread_id, body, author_name, created_at
                  FROM replies WHERE reply_id = ?
            """, (reply_id,)).fetchone()
        return self._reply_payload(row)

    def set_locked(self, thread_id: object, locked: bool) -> bool:
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            return False
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE threads SET locked = ? WHERE thread_id = ? AND deleted = 0",
                (1 if locked else 0, thread_id),
            )
            return cursor.rowcount == 1

    def delete_thread(self, thread_id: object) -> bool:
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            return False
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE threads SET deleted = 1, locked = 1 WHERE thread_id = ? AND deleted = 0",
                (thread_id,),
            )
            return cursor.rowcount == 1

    def delete_reply(self, reply_id: object) -> bool:
        if not isinstance(reply_id, str) or not REPLY_ID_PATTERN.fullmatch(reply_id):
            return False
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE replies SET deleted = 1 WHERE reply_id = ? AND deleted = 0",
                (reply_id,),
            )
            return cursor.rowcount == 1

    def moderation_snapshot(self, *, limit: int = 100) -> list[dict]:
        """Recent threads and replies for the operator moderation CLI."""
        limit = max(1, min(int(limit), 500))
        with closing(self._connect()) as db:
            threads = db.execute("""
                SELECT thread_id, title, author_name, created_at, locked, deleted
                  FROM threads ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            replies = db.execute("""
                SELECT reply_id, thread_id, body, author_name, created_at, deleted
                  FROM replies ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [
            {
                "kind": "thread",
                "id": row["thread_id"],
                "title": row["title"],
                "author": row["author_name"],
                "created_at": int(row["created_at"]),
                "locked": bool(row["locked"]),
                "deleted": bool(row["deleted"]),
            }
            for row in threads
        ] + [
            {
                "kind": "reply",
                "id": row["reply_id"],
                "thread_id": row["thread_id"],
                "excerpt": row["body"][:120],
                "author": row["author_name"],
                "created_at": int(row["created_at"]),
                "deleted": bool(row["deleted"]),
            }
            for row in replies
        ]
