"""Local community forum storage for the StreamioV host.

The forum is a separate SQLite database. Reads are public; every write needs an
authenticated host session. This module contains no HTTP handling so it can be
tested and moderated from the operator CLI.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
import json
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
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REPORT_REASONS = {"spam", "harassment", "offtopic", "other"}
REPORT_DECISIONS = {"resolved", "dismissed"}
CONTENT_ACTIONS = {"none", "delete", "lock", "unlock"}
REPORT_DETAIL_MAX = 500
REPORT_TARGET_PREVIEW_LENGTH = 120
SPAM_LINK_LIMIT = 4
SPAM_REPEAT_RUN = 8
DAY_SECONDS = 86_400
DELETED_CONTENT_RETENTION_DAYS = 90
REPORT_RETENTION_DAYS = 90
MODERATION_ACTION_RETENTION_DAYS = 180
READ_NOTIFICATION_RETENTION_DAYS = 30
UNREAD_NOTIFICATION_RETENTION_DAYS = 90


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


def validate_report_reason(value: object) -> str:
    if not isinstance(value, str) or value not in REPORT_REASONS:
        raise ForumError("Ungültiger Meldegrund.")
    return value


def validate_report_detail(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ForumError("Detail muss Text sein.")
    if len(value) > REPORT_DETAIL_MAX:
        raise ForumError(f"Detail darf höchstens {REPORT_DETAIL_MAX} Zeichen enthalten.")
    if "\x00" in value:
        raise ForumError("Detail enthält ungültige Zeichen.")
    return value.strip()


def static_spam_flags(text: str) -> list[str]:
    flags = []
    if re.search(r"(.)\1{" + str(SPAM_REPEAT_RUN - 1) + r",}", text):
        flags.append("repeated_characters")
    if len(re.findall(r"https?://|www\.", text, re.IGNORECASE)) >= SPAM_LINK_LIMIT:
        flags.append("many_links")
    letters = [character for character in text if character.isalpha()]
    if len(letters) >= 20 and sum(character.isupper() for character in letters) / len(letters) > 0.8:
        flags.append("mostly_capitals")
    return flags


def _decode_spam_flags(value: object) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [flag for flag in decoded if isinstance(flag, str)]


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

    @contextmanager
    def _write_transaction(self):
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.rollback()
                raise
            else:
                db.commit()

    @staticmethod
    def _ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        present = {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in present:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _spam_flags(db: sqlite3.Connection, *, table: str, id_column: str, identifier: str,
                    body: str, created_at: int) -> list[str]:
        flags = static_spam_flags(body)
        duplicate = db.execute(
            f"SELECT 1 FROM {table} WHERE {id_column} != ? AND body = ? "
            "AND created_at BETWEEN ? AND ? AND deleted = 0 LIMIT 1",
            (identifier, body, int(created_at) - 600, int(created_at) + 600),
        ).fetchone()
        if duplicate is not None:
            flags.append("recent_duplicate")
        return flags

    def _initialize(self) -> None:
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS threads (
                        thread_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        body TEXT NOT NULL,
                        author_user_id TEXT NOT NULL,
                        author_name TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        locked INTEGER NOT NULL DEFAULT 0,
                        deleted INTEGER NOT NULL DEFAULT 0
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS replies (
                        reply_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
                        body TEXT NOT NULL,
                        author_user_id TEXT NOT NULL,
                        author_name TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        deleted INTEGER NOT NULL DEFAULT 0
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS forum_reports (
                        report_id TEXT PRIMARY KEY,
                        thread_id TEXT,
                        reply_id TEXT,
                        reason TEXT NOT NULL,
                        detail TEXT NOT NULL DEFAULT '',
                        reporter_user_id TEXT NOT NULL DEFAULT 'unknown',
                        status TEXT NOT NULL DEFAULT 'open',
                        created_at INTEGER NOT NULL,
                        resolved_at INTEGER,
                        resolved_by TEXT,
                        target_kind TEXT NOT NULL DEFAULT '',
                        target_key TEXT NOT NULL DEFAULT '',
                        target_title TEXT NOT NULL DEFAULT '',
                        target_body TEXT NOT NULL DEFAULT '',
                        target_author_user_id TEXT NOT NULL DEFAULT '',
                        target_author_name TEXT NOT NULL DEFAULT '',
                        target_thread_id TEXT NOT NULL DEFAULT '',
                        target_spam_flags TEXT NOT NULL DEFAULT '[]'
                    )
                """)
                self._ensure_columns(db, "threads", {
                    "locked": "INTEGER NOT NULL DEFAULT 0",
                    "deleted": "INTEGER NOT NULL DEFAULT 0",
                    "deleted_at": "INTEGER",
                })
                self._ensure_columns(db, "replies", {
                    "deleted": "INTEGER NOT NULL DEFAULT 0",
                    "deleted_at": "INTEGER",
                })
                db.execute(
                    "UPDATE threads SET deleted_at = created_at "
                    "WHERE deleted = 1 AND deleted_at IS NULL"
                )
                db.execute(
                    "UPDATE replies SET deleted_at = created_at "
                    "WHERE deleted = 1 AND deleted_at IS NULL"
                )
                self._ensure_columns(db, "forum_reports", {
                    "detail": "TEXT NOT NULL DEFAULT ''",
                    "reporter_user_id": "TEXT NOT NULL DEFAULT 'unknown'",
                    "status": "TEXT NOT NULL DEFAULT 'open'",
                    "resolved_at": "INTEGER",
                    "resolved_by": "TEXT",
                    "target_kind": "TEXT NOT NULL DEFAULT ''",
                    "target_key": "TEXT NOT NULL DEFAULT ''",
                    "target_title": "TEXT NOT NULL DEFAULT ''",
                    "target_body": "TEXT NOT NULL DEFAULT ''",
                    "target_author_user_id": "TEXT NOT NULL DEFAULT ''",
                    "target_author_name": "TEXT NOT NULL DEFAULT ''",
                    "target_thread_id": "TEXT NOT NULL DEFAULT ''",
                    "target_spam_flags": "TEXT NOT NULL DEFAULT '[]'",
                })
                db.execute("""
                    CREATE TABLE IF NOT EXISTS forum_moderation_actions (
                        action_id TEXT PRIMARY KEY,
                        report_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        actor_user_id TEXT NOT NULL,
                        actor_name TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        created_at INTEGER NOT NULL
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS forum_notifications (
                        notification_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        report_id TEXT NOT NULL,
                        message TEXT NOT NULL,
                        read_at INTEGER,
                        created_at INTEGER NOT NULL
                    )
                """)
                self._backfill_report_context(db)
                self._dismiss_duplicate_reports(db)
                for statement in (
                    "CREATE INDEX IF NOT EXISTS threads_created ON threads(deleted, created_at)",
                    "CREATE INDEX IF NOT EXISTS replies_thread ON replies(thread_id, deleted, created_at)",
                    "CREATE INDEX IF NOT EXISTS reports_status_created ON forum_reports(status, created_at)",
                    "CREATE INDEX IF NOT EXISTS reports_target ON forum_reports(thread_id, reply_id)",
                    "CREATE INDEX IF NOT EXISTS moderation_actions_report "
                    "ON forum_moderation_actions(report_id, created_at)",
                    "CREATE INDEX IF NOT EXISTS notifications_user "
                    "ON forum_notifications(user_id, read_at, created_at)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS reports_open_unique "
                    "ON forum_reports(reporter_user_id, reason, target_key) WHERE status = 'open'",
                ):
                    db.execute(statement)
                db.commit()
            except BaseException:
                db.rollback()
                raise
        self._apply_permissions()

    def _backfill_report_context(self, db: sqlite3.Connection) -> None:
        db.execute("""
            UPDATE forum_reports
               SET target_kind = CASE WHEN target_kind <> '' THEN target_kind
                                      WHEN thread_id IS NOT NULL AND thread_id <> '' THEN 'thread'
                                      WHEN reply_id IS NOT NULL AND reply_id <> '' THEN 'reply'
                                      ELSE '' END,
                   target_key = CASE WHEN target_key <> '' THEN target_key
                                     WHEN thread_id IS NOT NULL AND thread_id <> '' THEN 'thread:' || thread_id
                                     WHEN reply_id IS NOT NULL AND reply_id <> '' THEN 'reply:' || reply_id
                                     ELSE '' END,
                   target_thread_id = CASE WHEN target_thread_id <> '' THEN target_thread_id
                                           WHEN thread_id IS NOT NULL AND thread_id <> '' THEN thread_id
                                           ELSE COALESCE((SELECT r.thread_id FROM replies r
                                                           WHERE r.reply_id = forum_reports.reply_id), '') END,
                   target_title = CASE WHEN target_title <> '' THEN target_title
                                       ELSE COALESCE(
                                         (SELECT t.title FROM threads t
                                           WHERE t.thread_id = forum_reports.thread_id),
                                         (SELECT t.title FROM threads t
                                           JOIN replies r ON r.thread_id = t.thread_id
                                          WHERE r.reply_id = forum_reports.reply_id), '') END,
                   target_body = CASE WHEN target_body <> '' THEN target_body
                                      ELSE COALESCE(
                                        (SELECT t.body FROM threads t
                                          WHERE t.thread_id = forum_reports.thread_id),
                                        (SELECT r.body FROM replies r
                                          WHERE r.reply_id = forum_reports.reply_id), '') END,
                   target_author_user_id = CASE WHEN target_author_user_id <> '' THEN target_author_user_id
                                                ELSE COALESCE(
                                                  (SELECT t.author_user_id FROM threads t
                                                    WHERE t.thread_id = forum_reports.thread_id),
                                                  (SELECT r.author_user_id FROM replies r
                                                    WHERE r.reply_id = forum_reports.reply_id), '') END,
                   target_author_name = CASE WHEN target_author_name <> '' THEN target_author_name
                                             ELSE COALESCE(
                                               (SELECT t.author_name FROM threads t
                                                 WHERE t.thread_id = forum_reports.thread_id),
                                               (SELECT r.author_name FROM replies r
                                                 WHERE r.reply_id = forum_reports.reply_id), '') END
        """)
        rows = db.execute("""
            SELECT report_id, target_kind, target_body, target_thread_id, thread_id, reply_id, created_at
              FROM forum_reports
             WHERE target_spam_flags = '[]' AND target_body <> ''
        """).fetchall()
        for row in rows:
            if row["target_kind"] == "thread":
                flags = self._spam_flags(
                    db, table="threads", id_column="thread_id",
                    identifier=row["thread_id"], body=row["target_body"],
                    created_at=row["created_at"],
                )
            elif row["target_kind"] == "reply":
                flags = self._spam_flags(
                    db, table="replies", id_column="reply_id",
                    identifier=row["reply_id"], body=row["target_body"],
                    created_at=row["created_at"],
                )
            else:
                continue
            if flags:
                db.execute(
                    "UPDATE forum_reports SET target_spam_flags = ? WHERE report_id = ?",
                    (json.dumps(flags), row["report_id"]),
                )

    def _dismiss_duplicate_reports(self, db: sqlite3.Connection) -> None:
        duplicates = db.execute("""
            SELECT r.report_id, r.reporter_user_id, r.target_key
              FROM forum_reports r
             WHERE r.status = 'open'
               AND EXISTS (
                 SELECT 1 FROM forum_reports older
                  WHERE older.status = 'open'
                    AND older.reporter_user_id = r.reporter_user_id
                    AND older.reason = r.reason
                    AND older.target_key = r.target_key
                    AND (older.created_at < r.created_at
                         OR (older.created_at = r.created_at AND older.rowid < r.rowid))
               )
             ORDER BY r.created_at ASC, r.rowid ASC
        """).fetchall()
        if not duplicates:
            return
        now = int(time.time())
        for row in duplicates:
            db.execute(
                "UPDATE forum_reports SET status = 'dismissed', resolved_at = ?, "
                "resolved_by = 'migration' WHERE report_id = ? AND status = 'open'",
                (now, row["report_id"]),
            )
            db.execute("""
                INSERT INTO forum_moderation_actions(
                    action_id, report_id, action, actor_user_id, actor_name, note, created_at
                ) VALUES(?,?,'dismissed','migration','migration','Dublette bei der Migration',?)
            """, (uuid.uuid4().hex, row["report_id"], now))

    def _apply_permissions(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = Path(str(self.database) + suffix)
            try:
                if path.exists():
                    os.chmod(path, 0o600)
            except OSError:
                pass

    @staticmethod
    def _thread_payload(row: sqlite3.Row, spam_flags: list[str] | None = None) -> dict:
        return {
            "id": row["thread_id"],
            "title": row["title"],
            "body": row["body"],
            "author": row["author_name"],
            "author_user_id": row["author_user_id"],
            "created_at": int(row["created_at"]),
            "locked": bool(row["locked"]),
            "reply_count": int(row["reply_count"]),
            "last_activity": int(row["last_activity"]),
            "spam_flags": list(spam_flags or []),
        }

    @staticmethod
    def _reply_payload(row: sqlite3.Row, spam_flags: list[str] | None = None) -> dict:
        return {
            "id": row["reply_id"],
            "thread_id": row["thread_id"],
            "body": row["body"],
            "author": row["author_name"],
            "author_user_id": row["author_user_id"],
            "created_at": int(row["created_at"]),
            "spam_flags": list(spam_flags or []),
        }

    def list_threads(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        with closing(self._connect()) as db:
            rows = db.execute("""
                SELECT t.thread_id, t.title, t.body, t.author_name, t.author_user_id, t.created_at,
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
            payloads = []
            for row in rows:
                flags = self._spam_flags(
                    db, table="threads", id_column="thread_id",
                    identifier=row["thread_id"], body=row["body"],
                    created_at=row["created_at"],
                )
                payloads.append(self._thread_payload(row, flags))
        return payloads

    def get_thread(self, thread_id: object) -> dict | None:
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            return None
        with closing(self._connect()) as db:
            row = db.execute("""
                SELECT t.thread_id, t.title, t.body, t.author_name, t.author_user_id, t.created_at,
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
                SELECT reply_id, thread_id, body, author_name, author_user_id, created_at
                  FROM replies
                  WHERE thread_id = ? AND deleted = 0
                  ORDER BY created_at ASC
            """, (thread_id,)).fetchall()
            flags = self._spam_flags(
                db, table="threads", id_column="thread_id",
                identifier=row["thread_id"], body=row["body"],
                created_at=row["created_at"],
            )
            payload = self._thread_payload(row, flags)
            reply_payloads = []
            for reply in replies:
                reply_flags = self._spam_flags(
                    db, table="replies", id_column="reply_id",
                    identifier=reply["reply_id"], body=reply["body"],
                    created_at=reply["created_at"],
                )
                reply_payloads.append(self._reply_payload(reply, reply_flags))
        payload["replies"] = reply_payloads
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
                SELECT reply_id, thread_id, body, author_name, author_user_id, created_at
                  FROM replies WHERE reply_id = ?
            """, (reply_id,)).fetchone()
            flags = self._spam_flags(
                db, table="replies", id_column="reply_id",
                identifier=reply_id, body=clean_body, created_at=now,
            )
        return self._reply_payload(row, flags)

    @staticmethod
    def _set_locked_db(db: sqlite3.Connection, thread_id: object, locked: bool) -> bool:
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            return False
        cursor = db.execute(
            "UPDATE threads SET locked = ? WHERE thread_id = ? AND deleted = 0",
            (1 if locked else 0, thread_id),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _delete_thread_db(db: sqlite3.Connection, thread_id: object) -> bool:
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            return False
        cursor = db.execute(
            "UPDATE threads SET deleted = 1, locked = 1, deleted_at = ? "
            "WHERE thread_id = ? AND deleted = 0",
            (int(time.time()), thread_id),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _delete_reply_db(db: sqlite3.Connection, reply_id: object) -> bool:
        if not isinstance(reply_id, str) or not REPLY_ID_PATTERN.fullmatch(reply_id):
            return False
        cursor = db.execute(
            "UPDATE replies SET deleted = 1, deleted_at = ? "
            "WHERE reply_id = ? AND deleted = 0",
            (int(time.time()), reply_id),
        )
        return cursor.rowcount == 1

    def set_locked(self, thread_id: object, locked: bool) -> bool:
        with self._transaction() as db:
            return self._set_locked_db(db, thread_id, locked)

    def delete_thread(self, thread_id: object) -> bool:
        with self._transaction() as db:
            return self._delete_thread_db(db, thread_id)

    def delete_reply(self, reply_id: object) -> bool:
        with self._transaction() as db:
            return self._delete_reply_db(db, reply_id)

    @staticmethod
    def _report_payload(row: sqlite3.Row) -> dict:
        kind = row["target_kind"] or (
            "thread" if row["thread_id"] else "reply" if row["reply_id"] else ""
        )
        flags = _decode_spam_flags(row["target_spam_flags"])
        body = row["target_body"] or ""
        thread_anchor = row["target_thread_id"] or row["thread_id"] or ""
        permalink = "/forum/#t=" + thread_anchor if thread_anchor else ""
        if kind == "reply" and row["reply_id"] and permalink:
            permalink += "&r=" + row["reply_id"]
        return {
            "id": row["report_id"],
            "report_id": row["report_id"],
            "thread_id": row["thread_id"],
            "reply_id": row["reply_id"],
            "kind": kind,
            "target_id": row["thread_id"] if kind == "thread" else row["reply_id"],
            "target_key": row["target_key"],
            "reason": row["reason"],
            "detail": row["detail"],
            "reporter_user_id": row["reporter_user_id"],
            "status": row["status"],
            "created_at": int(row["created_at"]),
            "resolved_at": row["resolved_at"],
            "resolved_by": row["resolved_by"],
            "resolver": row["resolved_by"],
            "target_title": row["target_title"],
            "target_body": body,
            "target_preview": body[:REPORT_TARGET_PREVIEW_LENGTH],
            "target_author": row["target_author_name"],
            "target_author_name": row["target_author_name"],
            "target_author_user_id": row["target_author_user_id"],
            "target_thread_id": thread_anchor,
            "target_permalink": permalink,
            "target_spam_flags": flags,
            "captured_at": int(row["created_at"]),
        }

    @staticmethod
    def _audit_payload(row: sqlite3.Row) -> dict:
        return {
            "action_id": row["action_id"],
            "report_id": row["report_id"],
            "action": row["action"],
            "actor_user_id": row["actor_user_id"],
            "actor_name": row["actor_name"],
            "note": row["note"],
            "created_at": int(row["created_at"]),
        }

    @staticmethod
    def _notification_payload(row: sqlite3.Row) -> dict:
        return {
            "id": row["notification_id"],
            "notification_id": row["notification_id"],
            "user_id": row["user_id"],
            "report_id": row["report_id"],
            "message": row["message"],
            "read_at": row["read_at"],
            "created_at": int(row["created_at"]),
            "unread": row["read_at"] is None,
        }

    @staticmethod
    def _insert_audit(db: sqlite3.Connection, *, report_id: str, action: str, actor: User,
                      note: str, created_at: int) -> dict:
        action_id = uuid.uuid4().hex
        db.execute("""
            INSERT INTO forum_moderation_actions(
                action_id, report_id, action, actor_user_id, actor_name, note, created_at
            ) VALUES(?,?,?,?,?,?,?)
        """, (action_id, report_id, action, actor.user_id, actor.username, note, created_at))
        return {
            "action_id": action_id,
            "report_id": report_id,
            "action": action,
            "actor_user_id": actor.user_id,
            "actor_name": actor.username,
            "note": note,
            "created_at": created_at,
        }

    @staticmethod
    def _insert_notification(db: sqlite3.Connection, *, user_id: str, report_id: str,
                             message: str, created_at: int) -> dict:
        notification_id = uuid.uuid4().hex
        db.execute("""
            INSERT INTO forum_notifications(
                notification_id, user_id, report_id, message, read_at, created_at
            ) VALUES(?,?,?,?,NULL,?)
        """, (notification_id, user_id, report_id, message, created_at))
        return {
            "notification_id": notification_id,
            "user_id": user_id,
            "report_id": report_id,
            "message": message,
            "read_at": None,
            "created_at": created_at,
            "unread": True,
        }

    def create_report(self, user: User, *, reason: object, thread_id: object = None,
                      reply_id: object = None, detail: object = None) -> dict:
        if not isinstance(user, User):
            raise ForumError("Anmeldung erforderlich.")
        clean_reason = validate_report_reason(reason)
        clean_detail = validate_report_detail(detail)
        if (thread_id is None) == (reply_id is None):
            raise ForumError("Genau ein Ziel muss angegeben werden.")
        for name, value, pattern in (("thread", thread_id, THREAD_ID_PATTERN),
                                     ("reply", reply_id, REPLY_ID_PATTERN)):
            if value is not None and (not isinstance(value, str) or not pattern.fullmatch(value)):
                raise ForumError(f"{name} wurde nicht gefunden.")
        report_id = uuid.uuid4().hex
        now = int(time.time())
        with self._write_transaction() as db:
            if thread_id is not None:
                target = db.execute("""
                    SELECT thread_id, title, body, author_user_id, author_name, created_at
                      FROM threads WHERE thread_id = ? AND deleted = 0
                """, (thread_id,)).fetchone()
                if target is None:
                    raise ForumError("Ziel wurde nicht gefunden.")
                kind = "thread"
                target_thread_id = thread_id
                target_title = target["title"]
                target_body = target["body"]
                target_author_user_id = target["author_user_id"]
                target_author_name = target["author_name"]
                flags = self._spam_flags(
                    db, table="threads", id_column="thread_id", identifier=thread_id,
                    body=target_body, created_at=target["created_at"],
                )
                target_key = "thread:" + thread_id
            else:
                target = db.execute("""
                    SELECT r.reply_id, r.thread_id, r.body, r.author_user_id, r.author_name,
                           r.created_at, t.title AS thread_title
                      FROM replies r
                      JOIN threads t ON t.thread_id = r.thread_id
                     WHERE r.reply_id = ? AND r.deleted = 0 AND t.deleted = 0
                """, (reply_id,)).fetchone()
                if target is None:
                    raise ForumError("Ziel wurde nicht gefunden.")
                kind = "reply"
                target_thread_id = target["thread_id"]
                target_title = target["thread_title"]
                target_body = target["body"]
                target_author_user_id = target["author_user_id"]
                target_author_name = target["author_name"]
                flags = self._spam_flags(
                    db, table="replies", id_column="reply_id", identifier=reply_id,
                    body=target_body, created_at=target["created_at"],
                )
                target_key = "reply:" + reply_id
            duplicate = db.execute("""
                SELECT 1 FROM forum_reports
                 WHERE reporter_user_id = ? AND reason = ? AND target_key = ? AND status = 'open'
                 LIMIT 1
            """, (user.user_id, clean_reason, target_key)).fetchone()
            if duplicate is not None:
                raise ForumError("Dieses Ziel wurde bereits gemeldet.")
            try:
                db.execute("""
                    INSERT INTO forum_reports(
                        report_id, thread_id, reply_id, reason, detail, reporter_user_id,
                        status, created_at, target_kind, target_key, target_title, target_body,
                        target_author_user_id, target_author_name, target_thread_id,
                        target_spam_flags
                    ) VALUES(?,?,?,?,?,?,'open',?,?,?,?,?,?,?,?,?)
                """, (
                    report_id, thread_id, reply_id, clean_reason, clean_detail, user.user_id,
                    now, kind, target_key, target_title, target_body, target_author_user_id,
                    target_author_name, target_thread_id, json.dumps(flags),
                ))
            except sqlite3.IntegrityError as exc:
                raise ForumError("Dieses Ziel wurde bereits gemeldet.") from exc
            row = db.execute(
                "SELECT * FROM forum_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        return self._report_payload(row)

    def list_reports(self, *, status: str = "all", limit: int = 200) -> list[dict]:
        if status not in {"open", "resolved", "dismissed", "all"}:
            raise ForumError("Ungültiger Status.")
        limit = max(1, min(int(limit), 200))
        where = "" if status == "all" else "WHERE status = ?"
        parameters: tuple = () if status == "all" else (status,)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT * FROM forum_reports {where} ORDER BY created_at DESC LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        return [self._report_payload(row) for row in rows]

    def decide_report(self, report_id: object, decision: object, actor: object, *,
                      content_action: object = None, note: object = None) -> dict | None:
        if decision not in REPORT_DECISIONS:
            raise ForumError("Ungültiger Status.")
        if not isinstance(actor, User):
            raise ForumError("Anmeldung erforderlich.")
        clean_action = "none" if content_action is None else content_action
        if not isinstance(clean_action, str) or clean_action not in CONTENT_ACTIONS:
            raise ForumError("Ungültige Inhaltsaktion.")
        clean_note = validate_report_detail(note)
        if not isinstance(report_id, str) or not THREAD_ID_PATTERN.fullmatch(report_id):
            return None
        with self._write_transaction() as db:
            row = db.execute(
                "SELECT * FROM forum_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            if row is None or row["status"] != "open":
                return None
            kind = row["target_kind"] or (
                "thread" if row["thread_id"] else "reply" if row["reply_id"] else ""
            )
            target_id = row["thread_id"] if kind == "thread" else row["reply_id"]
            if clean_action != "none" and not target_id:
                raise ForumError("Ziel wurde nicht gefunden.")
            if kind == "reply" and clean_action in ("lock", "unlock"):
                raise ForumError("Antworten können nicht gesperrt werden.")
            now = int(time.time())
            cursor = db.execute("""
                UPDATE forum_reports
                   SET status = ?, resolved_at = ?, resolved_by = ?
                 WHERE report_id = ? AND status = 'open'
            """, (decision, now, actor.user_id, report_id))
            if cursor.rowcount != 1:
                return None
            applied = False
            content_audit = None
            if clean_action == "delete":
                applied = (self._delete_thread_db(db, target_id) if kind == "thread"
                           else self._delete_reply_db(db, target_id))
            elif clean_action == "lock" and kind == "thread":
                applied = self._set_locked_db(db, target_id, True)
            elif clean_action == "unlock" and kind == "thread":
                applied = self._set_locked_db(db, target_id, False)
            if applied:
                content_audit = self._insert_audit(
                    db, report_id=report_id, action="content_" + clean_action,
                    actor=actor, note=clean_note, created_at=now,
                )
            audit = self._insert_audit(
                db, report_id=report_id, action=decision, actor=actor,
                note=clean_note, created_at=now,
            )
            notification = None
            reporter = row["reporter_user_id"]
            if reporter and reporter != "unknown":
                message = (
                    "Deine Meldung wurde geprüft und als gelöst markiert."
                    if decision == "resolved"
                    else "Deine Meldung wurde geprüft und verworfen."
                )
                if applied:
                    message += {
                        "delete": " Der Beitrag wurde gelöscht.",
                        "lock": " Das Thema wurde gesperrt.",
                        "unlock": " Das Thema wurde entsperrt.",
                    }[clean_action]
                notification = self._insert_notification(
                    db, user_id=reporter, report_id=report_id,
                    message=message, created_at=now,
                )
            updated = db.execute(
                "SELECT * FROM forum_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        return {
            "report": self._report_payload(updated),
            "report_id": report_id,
            "decision": decision,
            "content_action": clean_action,
            "content_action_applied": applied,
            "audit": audit,
            "content_audit": content_audit,
            "notification": notification,
        }

    def resolve_report(self, report_id: object, *, status: str, resolver: User) -> bool:
        result = self.decide_report(report_id, status, resolver)
        return result is not None

    def list_notifications(self, user_id: object, unread_only: bool = False) -> list[dict]:
        if not isinstance(user_id, str) or not USER_ID_PATTERN.fullmatch(user_id):
            raise ForumError("Ungültiger Benutzer.")
        where = "WHERE user_id = ? AND read_at IS NULL" if unread_only else "WHERE user_id = ?"
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT * FROM forum_notifications {where} "
                "ORDER BY created_at DESC, rowid DESC LIMIT 100",
                (user_id,),
            ).fetchall()
        return [self._notification_payload(row) for row in rows]

    def mark_notification_read(self, notification_id: object, user_id: object) -> bool:
        if not isinstance(user_id, str) or not USER_ID_PATTERN.fullmatch(user_id):
            raise ForumError("Ungültiger Benutzer.")
        if (not isinstance(notification_id, str)
                or not THREAD_ID_PATTERN.fullmatch(notification_id)):
            return False
        with self._write_transaction() as db:
            row = db.execute("""
                SELECT read_at FROM forum_notifications
                 WHERE notification_id = ? AND user_id = ?
            """, (notification_id, user_id)).fetchone()
            if row is None:
                return False
            if row["read_at"] is None:
                db.execute(
                    "UPDATE forum_notifications SET read_at = ? WHERE notification_id = ?",
                    (int(time.time()), notification_id),
                )
            return True

    def retention_policy(self) -> dict:
        return {
            "visible_threads_and_replies": "kept",
            "open_reports": "kept",
            "resolved_reports_days": REPORT_RETENTION_DAYS,
            "moderation_actions_days": MODERATION_ACTION_RETENTION_DAYS,
            "read_notifications_days": READ_NOTIFICATION_RETENTION_DAYS,
            "unread_notifications_days": UNREAD_NOTIFICATION_RETENTION_DAYS,
            "deleted_content_days": DELETED_CONTENT_RETENTION_DAYS,
            "email_notifications": False,
        }

    def _retention_queries(self, now: int) -> tuple[dict, tuple[tuple[str, str, str, tuple], ...]]:
        policy = self.retention_policy()
        queries = (
            (
                "resolved_reports",
                "SELECT COUNT(*) FROM forum_reports WHERE status != 'open' "
                "AND COALESCE(resolved_at, created_at) < ?",
                "DELETE FROM forum_reports WHERE status != 'open' "
                "AND COALESCE(resolved_at, created_at) < ?",
                (now - policy["resolved_reports_days"] * DAY_SECONDS,),
            ),
            (
                "moderation_actions",
                "SELECT COUNT(*) FROM forum_moderation_actions WHERE created_at < ?",
                "DELETE FROM forum_moderation_actions WHERE created_at < ?",
                (now - policy["moderation_actions_days"] * DAY_SECONDS,),
            ),
            (
                "read_notifications",
                "SELECT COUNT(*) FROM forum_notifications "
                "WHERE read_at IS NOT NULL AND read_at < ?",
                "DELETE FROM forum_notifications "
                "WHERE read_at IS NOT NULL AND read_at < ?",
                (now - policy["read_notifications_days"] * DAY_SECONDS,),
            ),
            (
                "unread_notifications",
                "SELECT COUNT(*) FROM forum_notifications "
                "WHERE read_at IS NULL AND created_at < ?",
                "DELETE FROM forum_notifications "
                "WHERE read_at IS NULL AND created_at < ?",
                (now - policy["unread_notifications_days"] * DAY_SECONDS,),
            ),
            (
                "deleted_replies",
                "SELECT COUNT(*) FROM replies AS r WHERE "
                "(r.deleted = 1 AND COALESCE(r.deleted_at, r.created_at) < ?) OR EXISTS ("
                "SELECT 1 FROM threads AS t WHERE t.thread_id = r.thread_id "
                "AND t.deleted = 1 AND COALESCE(t.deleted_at, t.created_at) < ?)",
                "DELETE FROM replies AS r WHERE "
                "(r.deleted = 1 AND COALESCE(r.deleted_at, r.created_at) < ?) OR EXISTS ("
                "SELECT 1 FROM threads AS t WHERE t.thread_id = r.thread_id "
                "AND t.deleted = 1 AND COALESCE(t.deleted_at, t.created_at) < ?)",
                (
                    now - policy["deleted_content_days"] * DAY_SECONDS,
                    now - policy["deleted_content_days"] * DAY_SECONDS,
                ),
            ),
            (
                "deleted_threads",
                "SELECT COUNT(*) FROM threads "
                "WHERE deleted = 1 AND COALESCE(deleted_at, created_at) < ?",
                "DELETE FROM threads "
                "WHERE deleted = 1 AND COALESCE(deleted_at, created_at) < ?",
                (now - policy["deleted_content_days"] * DAY_SECONDS,),
            ),
        )
        return policy, queries

    def retention_status(self, *, now: int | None = None) -> dict:
        current = int(time.time()) if now is None else int(now)
        policy, queries = self._retention_queries(current)
        with closing(self._connect()) as db:
            eligible = {
                name: int(db.execute(select, parameters).fetchone()[0])
                for name, select, _, parameters in queries
            }
        return {
            "ok": True,
            "dry_run": True,
            "now": current,
            "policy": policy,
            "eligible": eligible,
        }

    def apply_retention(self, *, now: int | None = None) -> dict:
        current = int(time.time()) if now is None else int(now)
        policy, queries = self._retention_queries(current)
        with self._write_transaction() as db:
            eligible = {
                name: int(db.execute(select, parameters).fetchone()[0])
                for name, select, _, parameters in queries
            }
            deleted = {
                name: int(db.execute(delete, parameters).rowcount)
                for name, _, delete, parameters in queries
            }
        return {
            "ok": True,
            "dry_run": False,
            "now": current,
            "policy": policy,
            "eligible": eligible,
            "deleted": deleted,
        }

    def list_user_posts(self, user_id: object, *, limit: int = 50, offset: int = 0) -> list[dict]:
        if not isinstance(user_id, str) or not USER_ID_PATTERN.fullmatch(user_id):
            raise ForumError("Ungültiger Benutzer.")
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        with closing(self._connect()) as db:
            threads = db.execute("""
                SELECT thread_id, title, created_at
                  FROM threads
                 WHERE author_user_id = ? AND deleted = 0
                 ORDER BY created_at DESC LIMIT ? OFFSET ?
            """, (user_id, limit, offset)).fetchall()
            replies = db.execute("""
                SELECT r.reply_id, r.thread_id, r.body, r.created_at
                  FROM replies r
                  JOIN threads t ON t.thread_id = r.thread_id
                 WHERE r.author_user_id = ? AND r.deleted = 0 AND t.deleted = 0
                 ORDER BY r.created_at DESC LIMIT ? OFFSET ?
            """, (user_id, limit, offset)).fetchall()
        return [
            {
                "kind": "thread",
                "id": row["thread_id"],
                "title": row["title"],
                "author_user_id": user_id,
                "created_at": int(row["created_at"]),
            }
            for row in threads
        ] + [
            {
                "kind": "reply",
                "id": row["reply_id"],
                "thread_id": row["thread_id"],
                "excerpt": row["body"][:120],
                "author_user_id": user_id,
                "created_at": int(row["created_at"]),
            }
            for row in replies
        ]

    def moderation_snapshot(self, *, limit: int = 100) -> list[dict]:
        """Recent threads and replies for the operator moderation CLI."""
        limit = max(1, min(int(limit), 500))
        with closing(self._connect()) as db:
            threads = db.execute("""
                SELECT thread_id, title, author_name, author_user_id, created_at, locked, deleted
                  FROM threads ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            replies = db.execute("""
                SELECT reply_id, thread_id, body, author_name, author_user_id, created_at, deleted
                  FROM replies ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [
            {
                "kind": "thread",
                "id": row["thread_id"],
                "title": row["title"],
                "author": row["author_name"],
                "author_user_id": row["author_user_id"],
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
                "author_user_id": row["author_user_id"],
                "created_at": int(row["created_at"]),
                "deleted": bool(row["deleted"]),
            }
            for row in replies
        ]

    def spam_snapshot(self, *, limit: int = 100) -> list[dict]:
        """Visible posts carrying advisory spam signals for operator review."""
        limit = max(1, min(int(limit), 500))
        flagged = []
        with closing(self._connect()) as db:
            threads = db.execute("""
                SELECT thread_id, title, body, author_name, author_user_id, created_at
                  FROM threads WHERE deleted = 0
                 ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            for row in threads:
                flags = self._spam_flags(
                    db, table="threads", id_column="thread_id",
                    identifier=row["thread_id"], body=row["body"],
                    created_at=row["created_at"],
                )
                if flags:
                    flagged.append({
                        "kind": "thread",
                        "id": row["thread_id"],
                        "title": row["title"],
                        "author": row["author_name"],
                        "author_user_id": row["author_user_id"],
                        "created_at": int(row["created_at"]),
                        "spam_flags": flags,
                    })
            replies = db.execute("""
                SELECT r.reply_id, r.thread_id, r.body, r.author_name, r.author_user_id, r.created_at
                  FROM replies r
                  JOIN threads t ON t.thread_id = r.thread_id
                 WHERE r.deleted = 0 AND t.deleted = 0
                 ORDER BY r.created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            for row in replies:
                flags = self._spam_flags(
                    db, table="replies", id_column="reply_id",
                    identifier=row["reply_id"], body=row["body"],
                    created_at=row["created_at"],
                )
                if flags:
                    flagged.append({
                        "kind": "reply",
                        "id": row["reply_id"],
                        "thread_id": row["thread_id"],
                        "excerpt": row["body"][:120],
                        "author": row["author_name"],
                        "author_user_id": row["author_user_id"],
                        "created_at": int(row["created_at"]),
                        "spam_flags": flags,
                    })
        return flagged
