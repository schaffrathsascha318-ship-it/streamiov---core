"""Versioned local event ledger for the StreamioV host."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


EVENT_SCHEMA_VERSION = 1
EVENT_COLUMNS = (
    "event_id", "user_id", "schema_version", "source", "type", "severity",
    "occurred_at", "created_at", "data_json",
)
SOURCES = frozenset({"core", "studio", "game", "ai"})
TYPES = frozenset({
    "studio.scene.take",
    "studio.scene.program",
    "studio.game.detected",
    "studio.gameplay.observation",
    "studio.game.highlight",
    "studio.game.replay_marker",
    "studio.game.assistant_advice",
    "studio.game.frame_analysis",
    "studio.game.situation",
    "studio.game.replay_analyzed",
    "studio.game.profile_updated",
    "studio.game.strategy",
    "studio.game.voice_command",
    "studio.game.auto_detection",
    "studio.gift.effect_preview",
    "studio.platform.event.received",
    "studio.alert.keyword",
    "studio.alert.platform_event",
    "studio.stream.started",
    "studio.stream.stopped",
    "studio.stream.error",
    "studio.shield.changed",
    "studio.connection.changed",
    "core.health.changed",
    "ai.task.submitted",
    "wishbox.order.received",
    "wishbox.order.status",
    "wishbox.order.result",
})
SEVERITIES = frozenset({"info", "warning", "error"})
KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,48}$")
SENSITIVE_KEY_PATTERN = re.compile(
    r"token|secret|password|passwort|stream.?key|authorization|cookie|rtmp|destination|credential|state|code",
    re.IGNORECASE,
)
RTMP_PATTERN = re.compile(r"\brtmps?://[^\s]+", re.IGNORECASE)
MAX_DATA_KEYS = 30
MAX_STRING = 240
MAX_EVENT_BYTES = 4096


class EventValidationError(ValueError):
    """Safe-to-return event validation error."""


def _clean_text(value: object, field: str, *, max_length: int = MAX_STRING) -> str:
    if not isinstance(value, str):
        raise EventValidationError(f"{field} must be a string.")
    text = " ".join(value.split())
    if not text or len(text) > max_length or "\x00" in text:
        raise EventValidationError(f"{field} must be 1 to {max_length} characters.")
    return text


def _validate_event_id(value: object) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise EventValidationError("event_id must be a UUID.")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise EventValidationError("event_id must be a UUID.") from exc
    if str(parsed) != value.lower():
        raise EventValidationError("event_id must be a UUID.")
    return str(parsed)


def _validate_occurred_at(value: object) -> str:
    text = _clean_text(value, "occurred_at", max_length=40)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventValidationError("occurred_at must be an ISO 8601 timestamp.") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EventValidationError("occurred_at must include a timezone.")
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalise_data(value: object) -> dict:
    if not isinstance(value, dict) or len(value) > MAX_DATA_KEYS:
        raise EventValidationError(f"data must be an object with at most {MAX_DATA_KEYS} fields.")
    result: dict = {}
    for key, item in value.items():
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise EventValidationError("data keys must be short identifiers.")
        if SENSITIVE_KEY_PATTERN.search(key):
            result[key] = "[REDACTED]"
            continue
        if item is None or isinstance(item, bool):
            result[key] = item
        elif isinstance(item, int):
            if not -10**12 <= item <= 10**12:
                raise EventValidationError("data numbers are out of range.")
            result[key] = item
        elif isinstance(item, float):
            if not math.isfinite(item) or not -10**12 <= item <= 10**12:
                raise EventValidationError("data numbers are out of range.")
            result[key] = item
        elif isinstance(item, str):
            text = " ".join(item.split())[:MAX_STRING]
            result[key] = RTMP_PATTERN.sub("[RTMP-URL REDACTED]", text)
        else:
            raise EventValidationError("data values must be scalar.")
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        raise EventValidationError(f"data must stay below {MAX_EVENT_BYTES} bytes.")
    return result


def validate_event(value: object) -> dict:
    if not isinstance(value, dict):
        raise EventValidationError("event must be an object.")
    expected = {"event_id", "schema_version", "source", "type", "severity", "occurred_at", "data"}
    if set(value) != expected:
        raise EventValidationError("event has an invalid shape.")
    if value["schema_version"] != EVENT_SCHEMA_VERSION:
        raise EventValidationError("unsupported event schema version.")
    source = _clean_text(value["source"], "source", max_length=24)
    if source not in SOURCES:
        raise EventValidationError("unsupported event source.")
    event_type = _clean_text(value["type"], "type", max_length=80)
    if event_type not in TYPES:
        raise EventValidationError("unsupported event type.")
    severity = _clean_text(value["severity"], "severity", max_length=16)
    if severity not in SEVERITIES:
        raise EventValidationError("unsupported event severity.")
    return {
        "event_id": _validate_event_id(value["event_id"]),
        "schema_version": EVENT_SCHEMA_VERSION,
        "source": source,
        "type": event_type,
        "severity": severity,
        "occurred_at": _validate_occurred_at(value["occurred_at"]),
        "data": normalise_data(value["data"]),
    }


class EventStore:
    """Idempotent, owner-scoped SQLite ledger for real local events."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.database = self.data_dir / "events.sqlite3"
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
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_owner_created ON events(user_id, created_at);
            """)
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict:
        try:
            data = json.loads(row["data_json"])
        except (TypeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return {
            "event_id": row["event_id"],
            "user_id": row["user_id"],
            "schema_version": int(row["schema_version"]),
            "source": row["source"],
            "type": row["type"],
            "severity": row["severity"],
            "occurred_at": row["occurred_at"],
            "created_at": int(row["created_at"]),
            "data": data,
        }

    def publish(self, user_id: object, event: object) -> tuple[dict, bool]:
        if not isinstance(user_id, str) or not user_id:
            raise EventValidationError("Anmeldung erforderlich.")
        clean = validate_event(event)
        now = int(time.time())
        with self._transaction() as db:
            cursor = db.execute("""
                INSERT OR IGNORE INTO events(
                    event_id, user_id, schema_version, source, type, severity,
                    occurred_at, created_at, data_json
                ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                clean["event_id"], user_id, clean["schema_version"], clean["source"],
                clean["type"], clean["severity"], clean["occurred_at"], now,
                json.dumps(clean["data"], ensure_ascii=False, separators=(",", ":")),
            ))
            created = cursor.rowcount == 1
            row = db.execute(
                "SELECT * FROM events WHERE event_id = ? AND user_id = ?",
                (clean["event_id"], user_id),
            ).fetchone()
        if row is None:
            raise EventValidationError("Ereignis konnte nicht gespeichert werden.")
        return self._payload(row), created

    def list(self, user_id: object, *, limit: int = 50) -> list[dict]:
        if not isinstance(user_id, str) or not user_id:
            raise EventValidationError("Anmeldung erforderlich.")
        bounded = max(1, min(int(limit), 100))
        with closing(self._connect()) as db:
            rows = db.execute("""
                SELECT * FROM events WHERE user_id = ?
                 ORDER BY created_at DESC, rowid DESC LIMIT ?
            """, (user_id, bounded)).fetchall()
        return [self._payload(row) for row in rows]

    def count(self, user_id: object) -> int:
        if not isinstance(user_id, str) or not user_id:
            return 0
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT COUNT(*) FROM events WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def count_all(self) -> int:
        with closing(self._connect()) as db:
            row = db.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0]) if row else 0
