"""Local persistence for verified platform OAuth connections."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.oauth.token_crypto import TokenCrypto, TokenCryptoError


class ConnectionError(ValueError):
    pass


PLATFORMS = frozenset({"twitch", "tiktok"})
STATE_TTL_SECONDS = 600
DB_FILE = "platform_connections.sqlite3"
MAX_USER_ID_CHARS = 128
MAX_STATE_CHARS = 512


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def hash_state(state: str) -> str:
    if not state:
        raise ValueError("state must not be empty")
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        return utc_now() >= datetime.fromisoformat(expires_at)
    except ValueError:
        return True


class ConnectionStore:
    def __init__(self, data_dir: str | Path, crypto: TokenCrypto | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.path = self.data_dir / DB_FILE
        self.crypto = crypto or TokenCrypto(self.data_dir)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_connections (
                    user_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'disconnected',
                    authorization_status TEXT NOT NULL DEFAULT 'not_authorized',
                    authorization_state TEXT NOT NULL DEFAULT 'not_authorized',
                    oauth_state_hash TEXT,
                    oauth_state_expires_at TEXT,
                    code_verifier_encrypted TEXT,
                    redirect_uri TEXT,
                    requested_scopes_json TEXT NOT NULL DEFAULT '[]',
                    account_id TEXT,
                    account_name TEXT,
                    token_reference TEXT,
                    scopes_json TEXT NOT NULL DEFAULT '[]',
                    access_token_encrypted TEXT,
                    refresh_token_encrypted TEXT,
                    token_expires_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    connected_at TEXT,
                    disconnected_at TEXT,
                    last_verified_at TEXT,
                    connection_status TEXT NOT NULL DEFAULT 'disconnected',
                    authorization_method TEXT,
                    last_error TEXT,
                    last_error_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, platform)
                )
                """
            )
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(platform_connections)")}
            additions = {
                "code_verifier_encrypted": "TEXT",
                "redirect_uri": "TEXT",
                "requested_scopes_json": "TEXT NOT NULL DEFAULT '[]'",
                "last_error": "TEXT",
                "last_error_at": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE platform_connections ADD COLUMN {name} {definition}"
                    )
            db.execute(
                "CREATE INDEX IF NOT EXISTS platform_connections_state "
                "ON platform_connections(oauth_state_hash)"
            )
            db.commit()
        if self.path.is_file() and not self.path.is_symlink():
            os.chmod(self.path, 0o600)

    @staticmethod
    def _validate_user_id(user_id: Any) -> str:
        if isinstance(user_id, bool):
            raise ConnectionError("user_id must be a non-empty string")
        if isinstance(user_id, int):
            if user_id <= 0:
                raise ConnectionError("user_id must be a non-empty string")
            return str(user_id)
        if not isinstance(user_id, str) or not 1 <= len(user_id) <= MAX_USER_ID_CHARS:
            raise ConnectionError("user_id must be a non-empty string")
        if any(ord(char) < 32 or char == "\x7f" or char in "/\\" for char in user_id):
            raise ConnectionError("user_id contains unsupported characters")
        return user_id

    @staticmethod
    def _validate_platform(platform: str) -> str:
        if platform not in PLATFORMS:
            raise ConnectionError(f"platform must be one of: {', '.join(sorted(PLATFORMS))}")
        return platform

    @staticmethod
    def _validate_state(state: Any) -> str:
        if not isinstance(state, str) or not 1 <= len(state) <= MAX_STATE_CHARS:
            raise ConnectionError("state must be a short non-empty string")
        if any(ord(char) < 32 or char == "\x7f" for char in state):
            raise ConnectionError("state contains unsupported characters")
        return state

    @staticmethod
    def _validate_error_code(code: Any) -> str:
        if not isinstance(code, str) or not 1 <= len(code) <= 64:
            return "oauth_error"
        if any(not (char.isalnum() or char in "_:-.") for char in code):
            return "oauth_error"
        return code

    @staticmethod
    def _validate_account_id(account_id: Any) -> str:
        if not isinstance(account_id, str) or not account_id.strip() or len(account_id) > 256:
            raise ConnectionError("account_id must not be empty")
        return account_id.strip()

    @staticmethod
    def _validate_token(token: Any, name: str) -> str:
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ConnectionError(f"{name} must not be empty")
        return token

    @staticmethod
    def _json_value(value: Any, name: str) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ConnectionError(f"{name} must be JSON serializable") from exc

    @staticmethod
    def _validate_scopes(scopes: Any) -> list[str]:
        if scopes is None:
            return []
        if not isinstance(scopes, list) or any(
            not isinstance(item, str) or not item or len(item) > 128 for item in scopes
        ):
            raise ConnectionError("scopes must be a list of strings")
        return list(dict.fromkeys(scopes))

    def create_oauth_state(self, user_id: Any, platform: str, state: str | None = None, *,
                           code_verifier: str | None = None, redirect_uri: str | None = None,
                           scopes: list[str] | None = None) -> str:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        state = self._validate_state(state or secrets.token_urlsafe(32))
        if code_verifier is not None:
            code_verifier = self._validate_token(code_verifier, "code_verifier")
        if redirect_uri is not None and (
            not isinstance(redirect_uri, str) or not 1 <= len(redirect_uri) <= 2048
        ):
            raise ConnectionError("redirect_uri is invalid")
        scopes = self._validate_scopes(scopes)
        verifier_encrypted = (
            self.crypto.encrypt(code_verifier) if code_verifier is not None else None
        )
        now = utc_now_iso()
        expires_at = (utc_now() + timedelta(seconds=STATE_TTL_SECONDS)).isoformat()
        with closing(self._connect()) as db:
            db.execute(
                """
                INSERT INTO platform_connections (
                    user_id, platform, oauth_state_hash, oauth_state_expires_at,
                    code_verifier_encrypted, redirect_uri, requested_scopes_json,
                    last_error, last_error_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                ON CONFLICT(user_id, platform) DO UPDATE SET
                    oauth_state_hash = excluded.oauth_state_hash,
                    oauth_state_expires_at = excluded.oauth_state_expires_at,
                    code_verifier_encrypted = excluded.code_verifier_encrypted,
                    redirect_uri = excluded.redirect_uri,
                    requested_scopes_json = excluded.requested_scopes_json,
                    last_error = NULL,
                    last_error_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (user_id, platform, hash_state(state), expires_at, verifier_encrypted,
                 redirect_uri, self._json_value(scopes, "scopes"), now, now),
            )
            db.commit()
        return state

    def find_pending_oauth_state(self, platform: str, state: str) -> dict[str, Any] | None:
        try:
            platform = self._validate_platform(platform)
            state = self._validate_state(state)
        except ConnectionError:
            return None
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT user_id, code_verifier_encrypted, redirect_uri,
                       requested_scopes_json, oauth_state_expires_at
                FROM platform_connections
                WHERE platform = ? AND oauth_state_hash = ?
                """,
                (platform, hash_state(state)),
            ).fetchone()
        if row is None or _expired(row["oauth_state_expires_at"]):
            return None
        try:
            verifier = (self.crypto.decrypt(row["code_verifier_encrypted"])
                        if row["code_verifier_encrypted"] else None)
        except TokenCryptoError as exc:
            raise ConnectionError("Stored OAuth state cannot be decrypted.") from exc
        try:
            scopes = json.loads(row["requested_scopes_json"] or "[]")
        except json.JSONDecodeError:
            scopes = []
        return {
            "user_id": row["user_id"],
            "code_verifier": verifier,
            "redirect_uri": row["redirect_uri"],
            "scopes": scopes if isinstance(scopes, list) else [],
            "expires_at": row["oauth_state_expires_at"],
        }

    def verify_oauth_state(self, user_id: Any, platform: str, state: str) -> bool:
        if not state or not isinstance(state, str):
            return False
        try:
            user_id = self._validate_user_id(user_id)
            platform = self._validate_platform(platform)
        except ConnectionError:
            return False
        with closing(self._connect()) as db:
            row = db.execute(
                """
                SELECT oauth_state_hash, oauth_state_expires_at
                FROM platform_connections
                WHERE user_id = ? AND platform = ?
                """,
                (user_id, platform),
            ).fetchone()
        if row is None or not row[0]:
            return False
        if _expired(row[1]):
            return False
        return hmac.compare_digest(row[0], hash_state(state))

    def clear_oauth_state(self, user_id: Any, platform: str) -> None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        with closing(self._connect()) as db:
            db.execute(
                """
                UPDATE platform_connections
                SET oauth_state_hash = NULL, oauth_state_expires_at = NULL,
                    code_verifier_encrypted = NULL, redirect_uri = NULL,
                    requested_scopes_json = '[]', updated_at = ?
                WHERE user_id = ? AND platform = ?
                """,
                (utc_now_iso(), user_id, platform),
            )
            db.commit()

    def fail_oauth_state(self, platform: str, state: str, code: str) -> str | None:
        pending = self.find_pending_oauth_state(platform, state)
        if pending is None:
            return None
        self.record_oauth_error(pending["user_id"], platform, code)
        self.clear_oauth_state(pending["user_id"], platform)
        return pending["user_id"]

    def save_verified_connection(self, user_id: Any, platform: str, state: str,
                                 account_id: str, account_name: str | None,
                                 access_token: str, refresh_token: str | None,
                                 expires_at: str | None, scopes: list[str] | None = None,
                                 metadata: dict[str, Any] | None = None) -> None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        state = self._validate_state(state)
        account_id = self._validate_account_id(account_id)
        access_token = self._validate_token(access_token, "access_token")
        if refresh_token is not None:
            refresh_token = self._validate_token(refresh_token, "refresh_token")
        if account_name is not None and (
            not isinstance(account_name, str) or len(account_name) > 256
        ):
            raise ConnectionError("account_name is invalid")
        scopes = self._validate_scopes(scopes)
        if metadata is not None and not isinstance(metadata, dict):
            raise ConnectionError("metadata must be an object")

        access_encrypted = self.crypto.encrypt(access_token)
        refresh_encrypted = (
            self.crypto.encrypt(refresh_token) if refresh_token is not None else None
        )
        now = utc_now_iso()
        with closing(self._connect()) as db:
            row = db.execute(
                """
                SELECT oauth_state_hash, oauth_state_expires_at
                FROM platform_connections
                WHERE user_id = ? AND platform = ?
                """,
                (user_id, platform),
            ).fetchone()
            if row is None or not row[0] or _expired(row[1]):
                raise ConnectionError("No unexpired OAuth state exists for this connection.")
            if not hmac.compare_digest(row[0], hash_state(state)):
                raise ConnectionError("OAuth state does not match.")
            result = db.execute(
                """
                UPDATE platform_connections
                SET
                    status = 'connected',
                    authorization_status = 'authorized',
                    authorization_state = 'authorized',
                    account_id = ?,
                    account_name = ?,
                    token_reference = ?,
                    scopes_json = ?,
                    access_token_encrypted = ?,
                    refresh_token_encrypted = ?,
                    token_expires_at = ?,
                    metadata_json = ?,
                    connected_at = ?,
                    disconnected_at = NULL,
                    last_verified_at = ?,
                    connection_status = 'connected',
                    authorization_method = 'oauth2',
                    oauth_state_hash = NULL,
                    oauth_state_expires_at = NULL,
                    code_verifier_encrypted = NULL,
                    redirect_uri = NULL,
                    requested_scopes_json = '[]',
                    last_error = NULL,
                    last_error_at = NULL,
                    updated_at = ?
                WHERE user_id = ? AND platform = ?
                  AND oauth_state_hash = ? AND oauth_state_expires_at > ?
                """,
                (account_id, account_name, f"{platform}:{user_id}:{account_id}",
                 self._json_value(scopes, "scopes"), access_encrypted, refresh_encrypted,
                 expires_at, self._json_value(metadata or {}, "metadata"), now, now,
                 now, user_id, platform, hash_state(state), now),
            )
            if result.rowcount != 1:
                raise ConnectionError("OAuth state was already used.")
            db.commit()

    def update_tokens(self, user_id: Any, platform: str, access_token: str,
                      refresh_token: str | None = None, expires_at: str | None = None,
                      scopes: list[str] | None = None,
                      expected_refresh_token: str | None = None) -> None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        access_token = self._validate_token(access_token, "access_token")
        if refresh_token is not None:
            refresh_token = self._validate_token(refresh_token, "refresh_token")
        if expected_refresh_token is not None:
            expected_refresh_token = self._validate_token(
                expected_refresh_token, "expected_refresh_token"
            )
        scopes = self._validate_scopes(scopes)
        now = utc_now_iso()
        access_encrypted = self.crypto.encrypt(access_token)
        refresh_encrypted = (
            self.crypto.encrypt(refresh_token) if refresh_token is not None else None
        )
        with closing(self._connect()) as db:
            if expected_refresh_token is not None:
                row = db.execute(
                    """
                    SELECT refresh_token_encrypted
                    FROM platform_connections
                    WHERE user_id = ? AND platform = ?
                      AND status = 'connected' AND authorization_state = 'authorized'
                    """,
                    (user_id, platform),
                ).fetchone()
                if row is None:
                    raise ConnectionError("No authorized connection exists for token renewal.")
                try:
                    current_refresh = self.crypto.decrypt(row[0]) if row[0] else None
                except TokenCryptoError as exc:
                    raise ConnectionError("Stored refresh token could not be verified.") from exc
                if not current_refresh or not hmac.compare_digest(
                    current_refresh, expected_refresh_token
                ):
                    raise ConnectionError("OAuth refresh token was already rotated.")
            if refresh_encrypted is None:
                result = db.execute(
                    """
                    UPDATE platform_connections
                    SET access_token_encrypted = ?, token_expires_at = ?,
                        scopes_json = CASE WHEN ? = 1 THEN ? ELSE scopes_json END,
                        last_verified_at = ?, last_error = NULL, last_error_at = NULL,
                        connection_status = 'connected', updated_at = ?
                    WHERE user_id = ? AND platform = ?
                      AND status = 'connected' AND authorization_state = 'authorized'
                    """,
                    (access_encrypted, expires_at, int(scopes is not None),
                     self._json_value(scopes, "scopes"), now, now, user_id, platform),
                )
            else:
                result = db.execute(
                    """
                    UPDATE platform_connections
                    SET access_token_encrypted = ?, refresh_token_encrypted = ?,
                        token_expires_at = ?,
                        scopes_json = CASE WHEN ? = 1 THEN ? ELSE scopes_json END,
                        last_verified_at = ?, last_error = NULL, last_error_at = NULL,
                        connection_status = 'connected', updated_at = ?
                    WHERE user_id = ? AND platform = ?
                      AND status = 'connected' AND authorization_state = 'authorized'
                    """,
                    (access_encrypted, refresh_encrypted, expires_at,
                     int(scopes is not None), self._json_value(scopes, "scopes"),
                     now, now, user_id, platform),
                )
            if result.rowcount != 1:
                raise ConnectionError("No authorized connection exists for token renewal.")
            db.commit()

    def record_oauth_error(self, user_id: Any, platform: str, code: str) -> None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        code = self._validate_error_code(code)
        now = utc_now_iso()
        with closing(self._connect()) as db:
            db.execute(
                """
                UPDATE platform_connections
                SET authorization_status = CASE
                        WHEN status = 'connected' AND access_token_encrypted IS NOT NULL
                             AND authorization_state = 'authorized'
                        THEN authorization_status ELSE 'failed' END,
                    authorization_state = CASE
                        WHEN status = 'connected' AND access_token_encrypted IS NOT NULL
                             AND authorization_state = 'authorized'
                        THEN authorization_state ELSE 'error' END,
                    connection_status = CASE
                        WHEN status = 'connected' AND access_token_encrypted IS NOT NULL
                             AND authorization_state = 'authorized'
                        THEN connection_status ELSE 'error' END,
                    last_error = ?, last_error_at = ?, updated_at = ?
                WHERE user_id = ? AND platform = ?
                """,
                (code, now, now, user_id, platform),
            )
            db.commit()

    def mark_reauthorization_required(self, user_id: Any, platform: str, code: str) -> None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        code = self._validate_error_code(code)
        now = utc_now_iso()
        with closing(self._connect()) as db:
            db.execute(
                """
                UPDATE platform_connections
                SET status = 'disconnected',
                    authorization_status = 'failed',
                    authorization_state = 'error',
                    account_id = NULL,
                    account_name = NULL,
                    token_reference = NULL,
                    scopes_json = '[]',
                    access_token_encrypted = NULL,
                    refresh_token_encrypted = NULL,
                    token_expires_at = NULL,
                    metadata_json = '{}',
                    disconnected_at = ?,
                    last_verified_at = NULL,
                    connection_status = 'reauthorization_required',
                    authorization_method = NULL,
                    oauth_state_hash = NULL,
                    oauth_state_expires_at = NULL,
                    code_verifier_encrypted = NULL,
                    redirect_uri = NULL,
                    requested_scopes_json = '[]',
                    last_error = ?,
                    last_error_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND platform = ?
                """,
                (now, code, now, now, user_id, platform),
            )
            db.commit()

    def disconnect_platform(self, user_id: Any, platform: str) -> None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        now = utc_now_iso()
        with closing(self._connect()) as db:
            db.execute(
                """
                UPDATE platform_connections
                SET
                    status = 'disconnected',
                    authorization_status = 'not_authorized',
                    authorization_state = 'not_authorized',
                    account_id = NULL,
                    account_name = NULL,
                    token_reference = NULL,
                    scopes_json = '[]',
                    access_token_encrypted = NULL,
                    refresh_token_encrypted = NULL,
                    token_expires_at = NULL,
                    metadata_json = '{}',
                    connected_at = NULL,
                    disconnected_at = ?,
                    last_verified_at = NULL,
                    connection_status = 'disconnected',
                    authorization_method = NULL,
                    oauth_state_hash = NULL,
                    oauth_state_expires_at = NULL,
                    code_verifier_encrypted = NULL,
                    redirect_uri = NULL,
                    requested_scopes_json = '[]',
                    last_error = NULL,
                    last_error_at = NULL,
                    updated_at = ?
                WHERE user_id = ? AND platform = ?
                """,
                (now, now, user_id, platform),
            )
            db.commit()

    def get_connection_status(self, user_id: Any, platform: str) -> dict[str, Any] | None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT
                    platform, status, authorization_status, authorization_state,
                    account_id, account_name, token_reference, scopes_json,
                    token_expires_at, connected_at, disconnected_at,
                    last_verified_at, connection_status, authorization_method,
                    access_token_encrypted, refresh_token_encrypted,
                    oauth_state_hash, oauth_state_expires_at, last_error, last_error_at
                FROM platform_connections
                WHERE user_id = ? AND platform = ?
                """,
                (user_id, platform),
            ).fetchone()
        if row is None:
            return None
        expired = _expired(row["token_expires_at"])
        has_token = bool(
            row["status"] == "connected"
            and row["authorization_state"] == "authorized"
            and row["access_token_encrypted"]
        )
        connected = has_token and not expired
        connection_status = "expired" if expired and has_token else row["connection_status"]
        return {
            "platform": row["platform"],
            "status": row["status"],
            "authorization_status": row["authorization_status"],
            "authorization_state": row["authorization_state"],
            "account_id": row["account_id"],
            "account_name": row["account_name"],
            "token_reference": row["token_reference"],
            "scopes": self._safe_json_list(row["scopes_json"]),
            "token_expires_at": row["token_expires_at"],
            "connected_at": row["connected_at"],
            "disconnected_at": row["disconnected_at"],
            "last_verified_at": row["last_verified_at"],
            "connection_status": connection_status,
            "authorization_method": row["authorization_method"],
            "authorization_pending": bool(row["oauth_state_hash"]) and not _expired(row["oauth_state_expires_at"]),
            "refresh_available": bool(row["refresh_token_encrypted"]),
            "needs_reauthorization": connection_status == "reauthorization_required",
            "last_error": row["last_error"],
            "last_error_at": row["last_error_at"],
            "token_expired": expired,
            "connected": connected,
        }

    @staticmethod
    def _safe_json_list(raw: Any) -> list[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    def list_connections(self, user_id: Any) -> list[dict[str, Any]]:
        user_id = self._validate_user_id(user_id)
        statuses = []
        for platform in sorted(PLATFORMS):
            status = self.get_connection_status(user_id, platform)
            statuses.append(status or {
                "platform": platform,
                "status": "disconnected",
                "authorization_status": "not_authorized",
                "authorization_state": "not_authorized",
                "account_id": None,
                "account_name": None,
                "token_reference": None,
                "scopes": [],
                "token_expires_at": None,
                "connected_at": None,
                "disconnected_at": None,
                "last_verified_at": None,
                "connection_status": "disconnected",
                "authorization_method": None,
                "authorization_pending": False,
                "refresh_available": False,
                "needs_reauthorization": False,
                "last_error": None,
                "last_error_at": None,
                "token_expired": False,
                "connected": False,
            })
        return statuses

    def get_tokens(self, user_id: Any, platform: str) -> tuple[str, str | None] | None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        with closing(self._connect()) as db:
            row = db.execute(
                """
                SELECT access_token_encrypted, refresh_token_encrypted,
                       token_expires_at, status, authorization_state
                FROM platform_connections
                WHERE user_id = ? AND platform = ?
                """,
                (user_id, platform),
            ).fetchone()
        if row is None or not row[0]:
            return None
        if row[3] != "connected" or row[4] != "authorized" or _expired(row[2]):
            return None
        try:
            access_token = self.crypto.decrypt(row[0])
            refresh_token = self.crypto.decrypt(row[1]) if row[1] else None
        except TokenCryptoError as exc:
            raise ConnectionError("Stored platform tokens cannot be decrypted.") from exc
        return access_token, refresh_token

    def get_refresh_token(self, user_id: Any, platform: str) -> str | None:
        user_id = self._validate_user_id(user_id)
        platform = self._validate_platform(platform)
        with closing(self._connect()) as db:
            row = db.execute(
                """
                SELECT refresh_token_encrypted, status, authorization_state
                FROM platform_connections
                WHERE user_id = ? AND platform = ?
                """,
                (user_id, platform),
            ).fetchone()
        if row is None or not row[0]:
            return None
        if row[1] != "connected" or row[2] != "authorized":
            return None
        try:
            return self.crypto.decrypt(row[0])
        except TokenCryptoError as exc:
            raise ConnectionError("Stored refresh token cannot be decrypted.") from exc
