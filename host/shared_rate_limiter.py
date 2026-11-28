"""Shared-file SQLite rate limiter for StreamioV host throttles.

This limiter coordinates multiple host processes and multiple host data
directories that are pointed at the same explicitly configured SQLite file. It
is fail-closed: unavailable storage, an invalid key, or any storage error denies
the request. Client addresses are only stored as HMAC-SHA-256 buckets, never in
plaintext. A shared file on one machine or a shared filesystem is not a
distributed database service; independent machines without a shared filesystem
need separate files and therefore do not share a budget.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time


class SharedRateLimiterError(ValueError):
    """Invalid shared rate limiter configuration or storage state."""


class SharedRateLimiter:
    """Sliding-window throttle backed by one explicitly shared SQLite file."""

    def __init__(self, database_path: str | Path, *, namespace: str = "streamiov",
                 limit: int = 10, window_seconds: int = 900,
                 max_keys: int = 4096) -> None:
        if not isinstance(database_path, (str, Path)) or not str(database_path).strip():
            raise SharedRateLimiterError("Shared rate limiter database path is required.")
        if not isinstance(namespace, str) or not 1 <= len(namespace) <= 80 or "\x00" in namespace:
            raise SharedRateLimiterError("Shared rate limiter namespace is invalid.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100_000:
            raise SharedRateLimiterError("Shared rate limiter limit must be 1 to 100000.")
        if (not isinstance(window_seconds, int) or isinstance(window_seconds, bool)
                or not 1 <= window_seconds <= 86_400):
            raise SharedRateLimiterError("Shared rate limiter window must be 1 to 86400 seconds.")
        if not isinstance(max_keys, int) or isinstance(max_keys, bool) or not 1 <= max_keys <= 100_000:
            raise SharedRateLimiterError("Shared rate limiter key cap must be 1 to 100000.")
        self.namespace = namespace
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.database = Path(database_path).expanduser().resolve()
        self._bucket_key: bytes | None = None
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=15)
        db.execute("PRAGMA busy_timeout = 15000")
        return db

    def _ensure_schema(self) -> None:
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shared_rate_limit_meta (
                        key TEXT PRIMARY KEY,
                        value BLOB NOT NULL
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shared_rate_limit_attempts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bucket TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS shared_rate_limit_attempts_bucket_created
                    ON shared_rate_limit_attempts(bucket, created_at)
                    """
                )
                row = db.execute(
                    "SELECT value FROM shared_rate_limit_meta WHERE key='bucket_key'"
                ).fetchone()
                if row is None:
                    key_material = secrets.token_bytes(32)
                    db.execute(
                        "INSERT INTO shared_rate_limit_meta (key, value) VALUES ('bucket_key', ?)",
                        (key_material,),
                    )
                else:
                    key_material = bytes(row[0])
                if len(key_material) != 32:
                    raise SharedRateLimiterError("Shared rate limiter key is invalid.")
                db.commit()
                self._bucket_key = key_material
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
            try:
                os.chmod(self.database, 0o600)
            except OSError:
                pass
        except SharedRateLimiterError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise SharedRateLimiterError("Shared rate limiter storage is unavailable.") from exc

    def _bucket(self, action: str, address: str) -> str:
        if self._bucket_key is None:
            raise SharedRateLimiterError("Shared rate limiter key is unavailable.")
        normalized = f"{self.namespace}\0{action[:80]}\0{address[:80]}"
        return hmac.new(
            self._bucket_key, normalized.encode("utf-8", "replace"), hashlib.sha256
        ).hexdigest()

    def allow(self, action: str, address: str, *, now: float | None = None) -> bool:
        """Consume one attempt from the shared budget; deny on any storage error."""
        if self._bucket_key is None:
            return False
        current = time.time() if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            return False
        cutoff = float(current) - self.window_seconds
        try:
            bucket = self._bucket(action, address)
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "DELETE FROM shared_rate_limit_attempts WHERE created_at < ?", (cutoff,)
                )
                count = db.execute(
                    """
                    SELECT COUNT(*) FROM shared_rate_limit_attempts
                    WHERE bucket=? AND created_at >= ?
                    """,
                    (bucket, cutoff),
                ).fetchone()[0]
                if count >= self.limit:
                    db.commit()
                    return False
                known = db.execute(
                    "SELECT 1 FROM shared_rate_limit_attempts WHERE bucket=? LIMIT 1", (bucket,)
                ).fetchone()
                buckets = db.execute(
                    "SELECT COUNT(DISTINCT bucket) FROM shared_rate_limit_attempts"
                ).fetchone()[0]
                if known is None and buckets >= self.max_keys:
                    db.commit()
                    return False
                db.execute(
                    "INSERT INTO shared_rate_limit_attempts (bucket, created_at) VALUES (?, ?)",
                    (bucket, float(current)),
                )
                db.commit()
                return True
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return False

    def status(self, *, now: float | None = None) -> dict:
        """Read-only, bounded status report without client addresses."""
        current = time.time() if now is None else now
        try:
            db = self._connect()
            try:
                cutoff = float(current) - self.window_seconds
                attempts = db.execute(
                    "SELECT COUNT(*) FROM shared_rate_limit_attempts WHERE created_at >= ?",
                    (cutoff,),
                ).fetchone()[0]
            finally:
                db.close()
            return {
                "ok": True,
                "configured": True,
                "namespace": self.namespace,
                "database": str(self.database),
                "limit": self.limit,
                "window_seconds": self.window_seconds,
                "active_attempts": int(attempts),
                "production_status": "NOT_VERIFIED",
            }
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "configured": True, "error": str(exc)[:160],
                    "production_status": "NOT_VERIFIED"}

    @staticmethod
    def describe_utc(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
