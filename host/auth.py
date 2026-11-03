"""Local account and server-side session storage for the StreamioV host."""
from __future__ import annotations

from collections import defaultdict, deque
from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid


PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")
MAX_PASSWORD_CHARS = 1024


class AuthError(ValueError):
    """Safe-to-return account validation or conflict error."""


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    created_at: int


def validate_credentials(username: object, password: object, *, registration: bool) -> tuple[str, str]:
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise AuthError("Username must be 3–24 ASCII letters, digits, dots, dashes, or underscores.")
    if not isinstance(password, str) or len(password) > MAX_PASSWORD_CHARS:
        raise AuthError("Password is missing or exceeds the 1024-character limit.")
    if registration and len(password) < 12:
        raise AuthError("Password must contain at least 12 characters.")
    if not password:
        raise AuthError("Invalid credentials.")
    return username, password


def _derive(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def _encode_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(password, salt)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds_text, salt_hex, expected_hex = encoded.split("$", 3)
        rounds = int(rounds_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except (AttributeError, TypeError, ValueError):
        return False
    if (algorithm != "pbkdf2_sha256" or not 100_000 <= rounds <= 2_000_000
            or len(salt) < SALT_BYTES or len(expected) != 32):
        return False
    actual = _derive(password, salt, rounds)
    return hmac.compare_digest(actual, expected)


class AuthStore:
    """SQLite account store; raw passwords and session tokens are never persisted."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.database = self.data_dir / "accounts.sqlite3"
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
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash BLOB PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
            """)
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @staticmethod
    def _token_hash(token: str) -> bytes:
        return hashlib.sha256(token.encode("ascii")).digest()

    @staticmethod
    def _issue_session(db: sqlite3.Connection, user_id: str, now: int) -> str:
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                   (AuthStore._token_hash(token), user_id, now, now + SESSION_TTL_SECONDS))
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        return token

    @staticmethod
    def _public_user(row: sqlite3.Row) -> User:
        return User(row["user_id"], row["username"], int(row["created_at"]))

    def register(self, username: object, password: object) -> tuple[User, str]:
        name, secret = validate_credentials(username, password, registration=True)
        user_id = uuid.uuid4().hex
        now = int(time.time())
        password_hash = _encode_password(secret)
        try:
            with self._transaction() as db:
                db.execute("INSERT INTO users(user_id,username,password_hash,created_at) VALUES(?,?,?,?)",
                           (user_id, name, password_hash, now))
                row = db.execute("SELECT user_id,username,created_at FROM users WHERE user_id=?", (user_id,)).fetchone()
                token = self._issue_session(db, user_id, now)
        except sqlite3.IntegrityError as exc:
            raise AuthError("Account unavailable.") from exc
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass
        return self._public_user(row), token

    def login(self, username: object, password: object) -> tuple[User, str] | None:
        if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
            # Do comparable password work for malformed/unknown usernames.
            if isinstance(password, str) and 0 < len(password) <= MAX_PASSWORD_CHARS:
                _derive(password, b"streamiov-dummy-salt")
            return None
        if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD_CHARS:
            return None
        now = int(time.time())
        with self._transaction() as db:
            row = db.execute("SELECT user_id,username,password_hash,created_at FROM users WHERE username=? COLLATE NOCASE",
                             (username,)).fetchone()
            if row is None:
                _derive(password, b"streamiov-dummy-salt")
                return None
            if not _verify_password(password, row["password_hash"]):
                return None
            token = self._issue_session(db, row["user_id"], now)
            public_row = {"user_id": row["user_id"], "username": row["username"], "created_at": row["created_at"]}
        return User(public_row["user_id"], public_row["username"], int(public_row["created_at"])), token

    def user_for_token(self, token: str | None, *, now: int | None = None) -> User | None:
        if not isinstance(token, str) or not 40 <= len(token) <= 128:
            return None
        try:
            token_hash = self._token_hash(token)
        except UnicodeEncodeError:
            return None
        current = int(time.time()) if now is None else int(now)
        with self._transaction() as db:
            row = db.execute("""
                SELECT users.user_id, users.username, users.created_at
                FROM sessions JOIN users USING(user_id)
                WHERE sessions.token_hash=? AND sessions.expires_at>?
            """, (token_hash, current)).fetchone()
        return self._public_user(row) if row else None

    def revoke(self, token: str | None) -> None:
        if not isinstance(token, str) or not 40 <= len(token) <= 128:
            return
        try:
            token_hash = self._token_hash(token)
        except UnicodeEncodeError:
            return
        with self._transaction() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def reset_password(self, username: object, password: object) -> bool:
        name, secret = validate_credentials(username, password, registration=True)
        password_hash = _encode_password(secret)
        with self._transaction() as db:
            row = db.execute("SELECT user_id FROM users WHERE username=? COLLATE NOCASE", (name,)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE users SET password_hash=? WHERE user_id=?", (password_hash, row["user_id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass
        return True


class RequestRateLimiter:
    """Small in-memory per-IP throttle; no client address is written to disk."""

    def __init__(self, limit: int = 10, window_seconds: int = 900, max_keys: int = 4096) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, action: str, address: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        key = (action, address[:80])
        with self._lock:
            for old_key in list(self._attempts):
                items = self._attempts[old_key]
                while items and current - items[0] >= self.window_seconds:
                    items.popleft()
                if not items:
                    del self._attempts[old_key]
            if key not in self._attempts and len(self._attempts) >= self.max_keys:
                return False
            attempts = self._attempts[key]
            if len(attempts) >= self.limit:
                return False
            attempts.append(current)
            return True
