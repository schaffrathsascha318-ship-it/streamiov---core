#!/usr/bin/env python3
"""Self-hosted StreamioV homepage and local-account host (standard library only).

This staged host serves static files, local accounts, read-only local AI assistance,
and non-sensitive health. It deliberately does not expose OAuth or arbitrary write APIs.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import getpass
import html
import json
import mimetypes
import os
from pathlib import Path
import ipaddress
import secrets
import ssl
import sqlite3
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlsplit


VERSION = "0.1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# The complete public site (homepage, downloads, legal pages, account UI) lives
# in the Worker public directory. The older dist/streamiov-homepage copy only
# contained the homepage, so serving it produced broken navigation links.
DEFAULT_SITE_ROOT = PROJECT_ROOT / "dist" / "streamiov-homepage-worker" / "public"
DEFAULT_RAW_DATA_ROOT = PROJECT_ROOT / "data"
CATALOG_ROUTES = {
    "/api/v1/catalog": "summary",
    "/api/v1/catalog/gifts": "gifts",
    "/api/v1/catalog/games": "games",
    "/api/v1/music/library": "music",
    "/api/v1/studio/templates": "templates",
}
MUSIC_DENIAL_STATES = frozenset({
    "rights_unknown", "rights_restricted", "rights_unverified", "missing_local_audio",
    "content_blocked", "content_review_required", "content_rejected", "unknown_track",
    "track_not_in_local_catalogue",
})
HEALTH_SCHEMAS = {
    "accounts": ("accounts.sqlite3", {
        "users": ("user_id", "username", "password_hash", "created_at"),
        "sessions": ("token_hash", "user_id", "created_at", "expires_at"),
    }),
    "forum": ("forum.sqlite3", {
        "threads": ("thread_id", "title", "body", "author_user_id", "author_name",
                    "created_at", "locked", "deleted"),
        "replies": ("reply_id", "thread_id", "body", "author_user_id", "author_name",
                    "created_at", "deleted"),
        "forum_reports": ("report_id", "thread_id", "reply_id", "reason", "reporter_user_id",
                          "status", "created_at", "target_key", "target_title",
                          "target_body", "target_author_user_id", "target_spam_flags"),
        "forum_moderation_actions": ("action_id", "report_id", "action", "actor_user_id",
                                     "created_at"),
        "forum_notifications": ("notification_id", "user_id", "report_id", "message",
                                "created_at", "read_at"),
    }),
    "catalog": ("streamiov-data.sqlite3", {
        "meta": ("key", "value"),
        "gifts": ("gift_id", "name", "source", "updated_at"),
    }),
    "ai_tasks": ("ai_tasks.sqlite3", {
        "ai_tasks": ("task_id", "user_id", "request", "status", "created_at",
                     "updated_at", "answer", "error"),
    }),
    "events": ("events.sqlite3", {
        "events": ("event_id", "user_id", "schema_version", "source", "type",
                   "severity", "occurred_at", "created_at", "data_json"),
    }),
    "music_state": ("music.sqlite3", {
        "playlists": ("playlist_id", "owner_id", "name", "description", "origin", "prompt", "created_at", "updated_at"),
        "playlist_tracks": ("playlist_id", "position", "track_json"),
        "queue_items": ("owner_id", "position", "track_json"),
        "music_settings": ("owner_id", "settings_json", "updated_at"),
    }),
    "wishbox": ("wishbox.sqlite3", {
        "wish_orders": ("order_id", "user_id", "kind", "status", "agent", "description", "created_at"),
        "wish_history": ("entry_id", "order_id", "from_status", "to_status", "created_at"),
    }),
}
OPTIONAL_HEALTH_SCHEMAS = {
    "platforms": ("platform_connections.sqlite3", {
        "platform_connections": ("user_id", "platform", "status", "oauth_state_hash",
                                 "code_verifier_encrypted", "access_token_encrypted",
                                 "last_error", "created_at", "updated_at"),
    }),
}
STARTED_AT = time.monotonic()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from host.ai_tasks import AITaskError, AITaskStore
from host.auth import (AuthError, AuthStore, DurableRateLimiter,
                       RequestRateLimiter, User)
from host.backup import (BackupError, BackupScheduler, create_backup, list_backups,
                         prune_backups, restore_backup, verify_backup)
from host.data_store import DataStore
from host.event_store import EVENT_SCHEMA_VERSION, EventStore, EventValidationError
from host.forum import ForumError, ForumStore
from host.music_library import HostMusicLibrary, HostMusicLibraryError
from host.music_state import MusicStateError, MusicStateStore
from host.retention import ForumRetentionScheduler
from host.shared_rate_limiter import SharedRateLimiter, SharedRateLimiterError
from host.wishbox import WishboxError, WishboxStore
from services.oauth.connection_service import PLATFORMS as OAUTH_PLATFORMS
from services.oauth.connection_service import ConnectionError as OAuthConnectionError
from services.oauth.connection_service import ConnectionStore, STATE_TTL_SECONDS
from services.oauth.provider import OAuthProvider, OAuthProviderConfig, OAuthProviderError, platform_config_status
from services.oauth.token_crypto import TokenCryptoError


def _store_health(path: Path, required: dict[str, tuple[str, ...]]) -> dict:
    if not path.is_file() or path.is_symlink():
        return {"ok": False, "error": "database_missing"}
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            check = db.execute("PRAGMA quick_check(1)").fetchone()
            if not check or str(check[0]).lower() != "ok":
                return {"ok": False, "error": "database_corrupt"}
            missing = []
            for table, columns in required.items():
                present = {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}
                if not present:
                    missing.append(table)
                    continue
                missing.extend(f"{table}.{column}" for column in columns if column not in present)
            if missing:
                return {"ok": False, "error": "schema_drift", "missing": missing[:12]}
    except sqlite3.DatabaseError as exc:
        detail = str(exc).lower()
        error = ("database_corrupt" if "not a database" in detail or "malformed" in detail
                 else "database_unavailable")
        return {"ok": False, "error": error}
    except OSError:
        return {"ok": False, "error": "database_unavailable"}
    return {"ok": True}


def database_health(data_dir: str | Path) -> dict:
    root = Path(data_dir).resolve()
    stores = {
        name: _store_health(root / filename, required)
        for name, (filename, required) in HEALTH_SCHEMAS.items()
    }
    for name, (filename, required) in OPTIONAL_HEALTH_SCHEMAS.items():
        path = root / filename
        if path.is_file():
            stores[name] = _store_health(path, required)
    return {"ok": all(item["ok"] for item in stores.values()), "stores": stores}


def forum_moderator_ids() -> frozenset[str]:
    raw = os.environ.get("STREAMIOV_FORUM_MODERATORS", "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def oauth_platform_statuses(store: ConnectionStore | None) -> dict[str, dict]:
    statuses = {}
    for platform in sorted(OAUTH_PLATFORMS):
        info = platform_config_status(platform)
        info["encrypted_storage_ready"] = store is not None
        info["ready"] = bool(store is not None and info.get("configured"))
        statuses[platform] = info
    return statuses


def oauth_ready(store: ConnectionStore | None) -> bool:
    return any(item["ready"] for item in oauth_platform_statuses(store).values())


def local_ai_provider():
    from ai.providers.local_http import LocalOpenAICompatibleProvider, OllamaProvider, ProviderError

    kind = os.environ.get("STREAMIOV_MODEL_PROVIDER", "ollama").lower()
    model = os.environ.get("STREAMIOV_MODEL", "qwen2.5-coder:7b")
    url = os.environ.get("STREAMIOV_MODEL_URL")
    if kind == "ollama":
        return OllamaProvider(model, url or "http://127.0.0.1:11434")
    if kind == "openai-compatible-local":
        return LocalOpenAICompatibleProvider(model, url or "http://127.0.0.1:8000/v1")
    raise ProviderError("Host AI accepts local providers only; no cloud fallback is used.")


def local_ai_status() -> dict:
    from ai.providers.local_http import ProviderError

    kind = os.environ.get("STREAMIOV_MODEL_PROVIDER", "ollama").lower()
    model = os.environ.get("STREAMIOV_MODEL", "qwen2.5-coder:7b")
    try:
        result = local_ai_provider().check_ready()
        return {
            "provider": result.get("provider"),
            "model": result.get("model"),
            "reachable": bool(result.get("reachable")),
            "model_available": bool(result.get("model_available")),
            "ready": bool(result.get("ready")),
            "detail": str(result.get("detail", "No status detail."))[:300],
        }
    except (ProviderError, OSError, ValueError) as exc:
        return {
            "provider": kind,
            "model": model,
            "ready": False,
            "detail": f"Local model status unavailable: {type(exc).__name__}: {str(exc)[:200]}",
        }


def run_local_ai_task(request: str) -> dict:
    from ai.providers.local_http import ProviderError

    provider = local_ai_provider()
    status = provider.check_ready()
    if not status.get("ready"):
        raise ProviderError(str(status.get("detail", "Local model is not ready."))[:300])
    system = (
        "You are the local STREAMIOV Studio assistant. Answer the user in the language of the request. "
        "You have no tools and must not claim file edits, external actions, device control, account changes, "
        "or successful tests. Return exactly one JSON object with only an 'answer' string."
    )
    reply = provider.generate(system=system, messages=[{"role": "user", "content": request}])
    try:
        payload = json.loads(reply.content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProviderError("Local model returned invalid JSON.") from exc
    answer = payload.get("answer") if isinstance(payload, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise ProviderError("Local model returned no answer.")
    return {
        "ok": True,
        "answer": answer[:4000],
        "provider": reply.provider,
        "model": reply.model,
        "execution": "read_only_local_inference",
    }


def resolve_public_file(site_root: str | Path, request_path: str) -> Path | None:
    """Resolve a static URL inside site_root, rejecting traversal and symlinks."""
    root = Path(site_root).resolve()
    try:
        decoded = unquote(urlsplit(request_path).path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if not decoded.startswith("/") or "\x00" in decoded or "\\" in decoded:
        return None
    relative = decoded.lstrip("/")
    if not relative:
        relative = "index.html"
    elif decoded.endswith("/"):
        relative = relative.rstrip("/") + "/index.html"
    parts = Path(relative).parts
    if any(part in {".", ".."} or part.startswith(".") for part in parts):
        return None
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            return None
    # Directory URLs ("/download/") serve their index.html, matching normal
    # static-site behaviour instead of returning 404 for every section page.
    if candidate.is_dir():
        candidate = candidate / "index.html"
        if candidate.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def validate_tls_settings(host: str, cert_file: str | None, key_file: str | None) -> bool:
    """Require explicit TLS material for any non-loopback listener."""
    if bool(cert_file) != bool(key_file):
        raise ValueError("TLS certificate and key must be provided together.")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if not loopback and not (cert_file and key_file):
        raise ValueError("Non-loopback binds require --tls-cert and --tls-key; plaintext remote access is disabled.")
    return bool(cert_file and key_file)


def _strict_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


class StreamioVHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, site_root: Path, data_dir: Path, *,
                 tls_enabled: bool = False, trust_loopback_proxy: bool = False,
                 registration_open: bool = False, raw_data_root: Path | None = None,
                 music_root: Path | None = None,
                 shared_rate_limit_db: str | Path | None = None):
        self.site_root = site_root.resolve()
        self.data_dir = Path(data_dir).resolve()
        effective_raw_root = raw_data_root or DEFAULT_RAW_DATA_ROOT
        self.auth_store = AuthStore(data_dir)
        self.data_store = DataStore(data_dir, raw_data_root)
        self.forum_store = ForumStore(data_dir)
        self.ai_task_store = AITaskStore(data_dir)
        self.event_store = EventStore(data_dir)
        self.music_state_store = MusicStateStore(data_dir)
        try:
            self.connection_store: ConnectionStore | None = ConnectionStore(data_dir)
        except (TokenCryptoError, OSError, sqlite3.Error):
            self.connection_store = None
        self.music_catalog = HostMusicLibrary(
            effective_raw_root / "music" / "rights_catalog.json",
            music_root or data_dir / "music",
        )

        def publish_wishbox_event(user_id, event_type, data):
            self.event_store.publish(user_id, {
                "event_id": str(uuid.uuid4()),
                "schema_version": EVENT_SCHEMA_VERSION,
                "source": "ai",
                "type": event_type,
                "severity": "info",
                "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": data,
            })

        self.wishbox_store = WishboxStore(
            data_dir, music_catalog=self.music_catalog,
            event_publisher=publish_wishbox_event,
        )
        shared_db = (shared_rate_limit_db if shared_rate_limit_db is not None
                     else os.environ.get("STREAMIOV_SHARED_RATE_LIMIT_DB"))
        self.shared_rate_limit_status = None
        if shared_db:
            def shared(namespace: str, limit: int, window: int) -> SharedRateLimiter:
                return SharedRateLimiter(shared_db, namespace=namespace, limit=limit,
                                         window_seconds=window)
            self.auth_limiter = shared("auth", 10, 900)
            self.forum_thread_limiter = shared("forum-thread", 5, 600)
            self.forum_reply_limiter = shared("forum-reply", 20, 600)
            self.forum_report_limiter = shared("forum-report", 5, 600)
            self.forum_moderation_limiter = shared("forum-moderation", 10, 600)
            if self.connection_store is not None:
                self.oauth_limiter = shared("oauth", 12, 600)
            else:
                self.oauth_limiter = RequestRateLimiter(limit=12, window_seconds=600)
            self.event_limiter = shared("events", 60, 600)
            self.music_state_limiter = shared("music-state", 120, 600)
            self.wishbox_limiter = shared("wishbox", 30, 600)
            self.shared_rate_limit_status = self.auth_limiter.status()
        else:
            self.auth_limiter = RequestRateLimiter()
            self.forum_thread_limiter = RequestRateLimiter(limit=5, window_seconds=600)
            self.forum_reply_limiter = RequestRateLimiter(limit=20, window_seconds=600)
            self.forum_report_limiter = RequestRateLimiter(limit=5, window_seconds=600)
            self.forum_moderation_limiter = RequestRateLimiter(limit=10, window_seconds=600)
            if self.connection_store is not None:
                self.oauth_limiter = DurableRateLimiter(data_dir, limit=12, window_seconds=600)
            else:
                self.oauth_limiter = RequestRateLimiter(limit=12, window_seconds=600)
            self.event_limiter = RequestRateLimiter(limit=60, window_seconds=600)
            self.music_state_limiter = RequestRateLimiter(limit=120, window_seconds=600)
            self.wishbox_limiter = RequestRateLimiter(limit=30, window_seconds=600)
        self.oauth_refresh_lock = threading.Lock()
        self.auth_work_slots = threading.BoundedSemaphore(4)
        self.ai_work_slots = threading.BoundedSemaphore(2)
        self.tls_enabled = tls_enabled
        self.trust_loopback_proxy = trust_loopback_proxy
        self.registration_open = registration_open
        super().__init__(address, handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "StreamioVHost/" + VERSION
    sys_version = ""

    def log_message(self, _format: str, *_args) -> None:
        # Do not record client addresses, URLs, or query strings by default.
        return

    def setup(self) -> None:
        super().setup()
        self.request.settimeout(10)

    def _send_bytes(self, status: int, body: bytes, content_type: str, *,
                    cache: str = "no-store", cors_origin: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if cors_origin is not None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _json_with_headers(self, status: int, payload: dict, headers: tuple[tuple[str, str], ...] = ()) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def _auth_cookie_token(self) -> str | None:
        raw_cookie = self.headers.get("Cookie", "")
        if len(raw_cookie) > 4096:
            return None
        parsed = SimpleCookie()
        try:
            parsed.load(raw_cookie)
        except Exception:
            return None
        morsel = parsed.get("streamiov_session")
        return morsel.value if morsel else None

    def _request_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if not origin or not host:
            return False
        try:
            parsed = urlsplit(origin)
            expected_scheme = "https" if self._secure_request() else "http"
            return (parsed.scheme == expected_scheme and parsed.netloc.lower() == host.lower()
                    and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
                    and parsed.username is None and parsed.password is None)
        except ValueError:
            return False

    def _studio_client_request(self) -> bool:
        """Allow the local Electron main process to use cookie auth without Origin."""
        if self.headers.get("X-Streamiov-Client") != "studio":
            return False
        try:
            peer = ipaddress.ip_address(self.client_address[0])
        except (ValueError, TypeError, IndexError):
            return False
        return peer.is_loopback

    def _secure_request(self) -> bool:
        if self.server.tls_enabled:
            return True
        if not self.server.trust_loopback_proxy:
            return False
        try:
            peer = ipaddress.ip_address(self.client_address[0])
        except (ValueError, TypeError, IndexError):
            return False
        forwarded = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        return peer.is_loopback and forwarded == "https"

    def _client_address(self) -> str:
        address = self.client_address[0] if isinstance(self.client_address, tuple) else "unknown"
        if self.server.trust_loopback_proxy:
            try:
                peer = ipaddress.ip_address(address)
                if peer.is_loopback:
                    forwarded = self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
                    return str(ipaddress.ip_address(forwarded))[:80]
            except ValueError:
                pass
        return address[:80]

    def _read_json_object(self, *, max_bytes: int) -> dict:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        raw_length = self.headers.get("Content-Length")
        if content_type != "application/json":
            raise AuthError("Content-Type must be application/json.")
        if raw_length is None or len(raw_length) > 5 or not raw_length.isdigit():
            raise AuthError("Content-Length is required.")
        length = int(raw_length)
        if not 1 <= length <= max_bytes:
            raise AuthError(f"JSON body must be between 1 and {max_bytes} bytes.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"), object_pairs_hook=_strict_json_object)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise AuthError("Invalid JSON request.") from exc
        if not isinstance(payload, dict):
            raise AuthError("Request must be a JSON object.")
        return payload

    def _read_auth_json(self) -> dict:
        payload = self._read_json_object(max_bytes=8192)
        if set(payload) != {"username", "password"}:
            raise AuthError("Request must contain only username and password.")
        return payload

    def _read_ai_request(self) -> dict:
        payload = self._read_json_object(max_bytes=4096)
        if set(payload) != {"request"}:
            raise AuthError("Request must contain only request.")
        request = payload["request"]
        if not isinstance(request, str) or not 1 <= len(request.strip()) <= 2000:
            raise AuthError("Request text must be between 1 and 2000 characters.")
        return {"request": request.strip()}

    def _read_event_request(self) -> dict:
        payload = self._read_json_object(max_bytes=8192)
        if set(payload) != {"event"}:
            raise AuthError("Request must contain only event.")
        return payload

    def _session_cookie(self, token: str, *, clear: bool = False) -> tuple[str, str]:
        max_age = 0 if clear else 30 * 24 * 60 * 60
        value = "" if clear else token
        flags = ["Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={max_age}"]
        if self._secure_request():
            flags.append("Secure")
        return "Set-Cookie", "streamiov_session=" + value + "; " + "; ".join(flags)

    def _auth_request(self, path: str) -> bool:
        if path == "/api/v1/auth/me" and self.command == "GET":
            user = self.server.auth_store.user_for_token(self._auth_cookie_token())
            if user is None:
                self._json_with_headers(401, {"error": "authentication_required"})
            else:
                self._json_with_headers(200, {"ok": True, "user": {
                    "id": user.user_id, "username": user.username,
                    "created_at": user.created_at,
                    "is_forum_moderator": user.user_id in forum_moderator_ids(),
                }})
            return True

        actions = {
            "/api/v1/auth/register": "register",
            "/api/v1/auth/login": "login",
            "/api/v1/auth/logout": "logout",
        }
        action = actions.get(path)
        if action is None or self.command != "POST":
            return False
        if action == "register" and not self.server.registration_open:
            self._json_with_headers(403, {"error": "registration_closed"})
            return True
        # Browsers must present an exact same-origin header. The Electron main
        # process is not a browser and identifies itself explicitly instead.
        if not self._request_origin_allowed() and not self._studio_client_request():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return True
        if not self.server.auth_limiter.allow(action, self._client_address()):
            self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "900"),))
            return True
        if action == "logout":
            self.server.auth_store.revoke(self._auth_cookie_token())
            self._json_with_headers(200, {"ok": True}, (self._session_cookie("", clear=True),))
            return True
        try:
            payload = self._read_auth_json()
        except AuthError as exc:
            self._json_with_headers(400, {"error": str(exc)})
            return True
        if not self.server.auth_work_slots.acquire(blocking=False):
            self._json_with_headers(503, {"error": "authentication_busy"}, (("Retry-After", "2"),))
            return True
        try:
            if action == "register":
                try:
                    user, token = self.server.auth_store.register(payload["username"], payload["password"])
                except AuthError as exc:
                    status = 409 if str(exc) == "Account unavailable." else 400
                    self._json_with_headers(status, {"error": str(exc)})
                    return True
                self._json_with_headers(201, {"ok": True, "user": {
                    "id": user.user_id, "username": user.username, "created_at": user.created_at
                }}, (self._session_cookie(token),))
                return True
            result = self.server.auth_store.login(payload["username"], payload["password"])
            if result is None:
                self._json_with_headers(401, {"error": "invalid_credentials"})
                return True
            user, token = result
            self._json_with_headers(200, {"ok": True, "user": {
                "id": user.user_id, "username": user.username, "created_at": user.created_at
            }}, (self._session_cookie(token),))
            return True
        finally:
            self.server.auth_work_slots.release()

    def _ai_task_request(self) -> None:
        user = self.server.auth_store.user_for_token(self._auth_cookie_token())
        if user is None:
            self._json_with_headers(401, {"error": "authentication_required"})
            return
        if self.headers.get("X-Streamiov-Client") != "studio":
            self._json_with_headers(403, {"error": "studio_client_header_required"})
            return
        if not self.server.auth_limiter.allow("ai_task", self._client_address()):
            self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "60"),))
            return
        try:
            payload = self._read_ai_request()
        except AuthError as exc:
            self._json_with_headers(400, {"error": str(exc)})
            return
        if not self.server.ai_work_slots.acquire(blocking=False):
            self._json_with_headers(503, {"error": "ai_execution_busy"}, (("Retry-After", "2"),))
            return
        task = None
        try:
            from ai.providers.local_http import ProviderError

            try:
                task = self.server.ai_task_store.create(user.user_id, payload["request"])
                self.server.ai_task_store.mark_running(task["id"])
                result = run_local_ai_task(payload["request"])
                self.server.ai_task_store.complete(
                    task["id"], answer=result.get("answer", ""),
                    provider=result.get("provider", ""), model=result.get("model", ""),
                )
            except AITaskError as exc:
                self._json_with_headers(400, {"error": str(exc)})
                return
            except ProviderError as exc:
                detail = str(exc)[:300]
                if task is not None:
                    self.server.ai_task_store.fail(task["id"], detail)
                stored = self.server.ai_task_store.get(task["id"], user.user_id) if task else None
                self._json_with_headers(503, {
                    "error": "ai_execution_not_ready",
                    "detail": detail,
                    "ai_execution_ready": False,
                    "task_id": task["id"] if task else None,
                    "task": stored,
                })
                return
            except (OSError, ValueError, UnicodeError) as exc:
                detail = f"{type(exc).__name__}: {str(exc)[:200]}"
                if task is not None:
                    self.server.ai_task_store.fail(task["id"], detail)
                stored = self.server.ai_task_store.get(task["id"], user.user_id) if task else None
                self._json_with_headers(502, {
                    "error": "ai_execution_failed",
                    "detail": detail,
                    "task_id": task["id"] if task else None,
                    "task": stored,
                })
                return
            stored = self.server.ai_task_store.get(task["id"], user.user_id)
            response = dict(result)
            response.update({"task_id": task["id"], "task": stored})
            self._json_with_headers(200, response)
        finally:
            self.server.ai_work_slots.release()

    def _events_request(self, path: str, query: dict[str, list[str]]) -> bool:
        if path != "/api/v1/events":
            return False
        if self.command not in {"GET", "POST"}:
            self._method_not_allowed()
            return True
        user = self.server.auth_store.user_for_token(self._auth_cookie_token())
        if user is None:
            self._json_with_headers(401, {"error": "authentication_required"})
            return True
        if self.headers.get("X-Streamiov-Client") != "studio":
            self._json_with_headers(403, {"error": "studio_client_header_required"})
            return True
        if self.headers.get("Origin") and not self._request_origin_allowed():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return True
        if not self.headers.get("Origin") and not self._studio_client_request():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return True
        if not self.server.event_limiter.allow("events", self._client_address()):
            self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "60"),))
            return True
        if self.command == "GET":
            raw_limit = (query.get("limit") or ["50"])[0]
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                limit = 50
            try:
                events = self.server.event_store.list(user.user_id, limit=limit)
            except EventValidationError as exc:
                self._json_with_headers(400, {"error": str(exc)})
                return True
            self._json_with_headers(200, {
                "ok": True,
                "schema_version": EVENT_SCHEMA_VERSION,
                "events": events,
            })
            return True
        try:
            payload = self._read_event_request()
            event, created = self.server.event_store.publish(user.user_id, payload["event"])
        except (AuthError, EventValidationError) as exc:
            self._json_with_headers(400, {"error": str(exc)})
            return True
        self._json_with_headers(201 if created else 200, {
            "ok": True,
            "event": event,
            "duplicate": not created,
        })
        return True

    def _catalog_request(self, path: str) -> bool:
        """Serve the read-only catalog built from repository raw data."""
        kind = CATALOG_ROUTES.get(path)
        if kind is None:
            return False
        try:
            payload = self.server.data_store.catalog(kind)
        except (sqlite3.Error, OSError, ValueError):
            self._json(503, {
                "ok": False,
                "error": "catalog_unavailable",
                "detail": "Der lokale Rohdaten-Katalog ist nicht lesbar.",
            })
            return True
        self._json(200, payload)
        return True

    def _available_music_tracks(self, territory: str, usage: str = "live_stream") -> list[dict]:
        gate = self.server.music_catalog.gate(territory, usage)
        return [{
            "id": track["id"],
            "title": track["title"],
            "artist": track["artist"],
            "source": "rights_catalog",
            "catalogId": track["id"],
            "territory": territory,
            "usage": usage,
            "liveAllowed": track["allowed"] is True and usage == "live_stream",
            "rightsState": track["state"] if track["allowed"] and track["state"] == "playable" else "rights_unknown",
        } for track in gate["tracks"]]

    def _music_state_request(self, path: str, query: dict[str, list[str]]) -> bool:
        paths = {
            "/api/v1/music/state",
            "/api/v1/music/playlist",
            "/api/v1/music/ai-playlist",
        }
        if path not in paths:
            return False
        if self.command not in {"GET", "POST"}:
            self._method_not_allowed()
            return True
        user = self.server.auth_store.user_for_token(self._auth_cookie_token())
        if user is None:
            self._json_with_headers(401, {"error": "authentication_required"})
            return True
        if self.headers.get("X-Streamiov-Client") != "studio":
            self._json_with_headers(403, {"error": "studio_client_header_required"})
            return True
        if self.headers.get("Origin") and not self._request_origin_allowed():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return True
        if not self.headers.get("Origin") and not self._studio_client_request():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return True
        if not self.server.music_state_limiter.allow(user.user_id, self._client_address()):
            self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "60"),))
            return True
        if self.command == "GET":
            if path != "/api/v1/music/state":
                self._method_not_allowed()
                return True
            try:
                snapshot = self.server.music_state_store.snapshot(user.user_id)
            except (MusicStateError, sqlite3.Error, OSError) as exc:
                self._json_with_headers(400, {"ok": False, "error": str(exc)})
                return True
            self._json_with_headers(200, snapshot)
            return True
        try:
            payload = self._read_json_object(max_bytes=262144)
            action = payload.get("action")
            store = self.server.music_state_store
            details = payload.get("payload")
            if path == "/api/v1/music/state" and action == "saveQueue":
                result = store.save_queue(user.user_id, details)
            elif path == "/api/v1/music/playlist" and action == "save":
                result = store.save_playlist(user.user_id, details)
            elif path == "/api/v1/music/playlist" and action in {"delete", "load"}:
                playlist_id = details.get("playlistId") if isinstance(details, dict) else None
                if action == "delete":
                    result = store.delete_playlist(user.user_id, playlist_id)
                else:
                    result = store.load_playlist(user.user_id, playlist_id)
            elif path == "/api/v1/music/playlist" and action == "combine":
                result = store.combine_playlists(user.user_id, details)
            elif path == "/api/v1/music/ai-playlist" and action in {"create", "improve"}:
                territory = details.get("territory", "DE") if isinstance(details, dict) else "DE"
                territory = territory.upper() if isinstance(territory, str) else "DE"
                available = self._available_music_tracks(territory)
                if action == "create":
                    result = store.ai_playlist(user.user_id, details, available)
                else:
                    result = store.improve_playlist(user.user_id, details, available)
            else:
                self._json_with_headers(400, {"ok": False, "error": "unsupported_music_action"})
                return True
        except (AuthError, MusicStateError, HostMusicLibraryError) as exc:
            error = str(exc)
            status = 404 if error == "playlist_not_found" else 409 if error == "playlist limit reached" else 400
            self._json_with_headers(status, {"ok": False, "error": error})
            return True
        except (sqlite3.Error, OSError, ValueError, TypeError):
            self._json_with_headers(503, {"ok": False, "error": "music_state_unavailable"})
            return True
        self._json_with_headers(200, result)
        return True

    def _music_request(self, path: str, query: dict[str, list[str]]) -> bool:
        """Serve a fail-closed local rights gate; never expose filesystem paths."""
        if not path.startswith("/api/v1/music/") or path == "/api/v1/music/library":
            return False
        territory = (query.get("territory") or ["DE"])[0]
        usage = (query.get("usage") or ["live_stream"])[0]
        if len(territory) > 2 or len(usage) > 32:
            self._json(400, {"ok": False, "error": "invalid_music_request"})
            return True
        try:
            if path == "/api/v1/music/gate":
                self._json(200, self.server.music_catalog.gate(territory, usage))
                return True
            if path == "/api/v1/music/dossier":
                track_id = (query.get("track") or [""])[0]
                if len(track_id) > 64:
                    self._json(400, {"ok": False, "error": "invalid_track_id"})
                    return True
                self._json(200, self.server.music_catalog.dossier(track_id, territory, usage))
                return True
            prefix = "/api/v1/music/audio/"
            if path.startswith(prefix):
                track_id = unquote(path[len(prefix):])
                if len(track_id) > 64:
                    self._json(400, {"ok": False, "error": "invalid_track_id"})
                    return True
                try:
                    peer = ipaddress.ip_address(self._client_address())
                except (ValueError, TypeError):
                    peer = None
                if peer is None or not peer.is_loopback:
                    self._json(403, {"ok": False, "error": "audio_loopback_only"})
                    return True
                audio_path, _metadata = self.server.music_catalog.playable_audio(track_id, territory, usage)
                self._send_bytes(200, audio_path.read_bytes(),
                                 mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream",
                                 cors_origin="null")
                return True
        except HostMusicLibraryError as exc:
            code = str(exc)
            if code == "music_catalog_unavailable":
                status = 503
            elif code in MUSIC_DENIAL_STATES:
                status = 403
            elif code == "audio_file_too_large":
                status = 413
            elif code in {"territory_required", "usage_not_supported", "invalid_track_id"}:
                status = 400
            else:
                status = 404
            self._json(status, {"ok": False, "error": code})
            return True
        except (OSError, ValueError):
            self._json(503, {"ok": False, "error": "music_audio_unavailable"})
            return True
        self._json(404, {"ok": False, "error": "not_found"})
        return True

    def _forum_request(self, path: str, query: dict[str, list[str]]) -> bool:
        """Public forum reads; authenticated, same-origin, rate-limited writes."""
        if path == "/api/forum/reports":
            if self.command == "GET":
                user = self.server.auth_store.user_for_token(self._auth_cookie_token())
                if user is None:
                    self._json(401, {"error": "authentication_required"})
                    return True
                if user.user_id not in forum_moderator_ids():
                    self._json(403, {"error": "moderator_required"})
                    return True
                status = (query.get("status") or ["all"])[0]
                try:
                    limit = int((query.get("limit") or ["200"])[0])
                except ValueError:
                    limit = 200
                try:
                    reports = self.server.forum_store.list_reports(status=status, limit=limit)
                except ForumError as exc:
                    self._json(400, {"error": str(exc)})
                    return True
                self._json(200, {"ok": True, "status": status, "reports": reports})
                return True
            if self.command != "POST":
                self._json(405, {"error": "method_not_allowed"})
                return True
            if not self._request_origin_allowed():
                self._json(403, {"error": "request_origin_not_allowed"})
                return True
            user = self.server.auth_store.user_for_token(self._auth_cookie_token())
            if user is None:
                self._json(401, {"error": "authentication_required"})
                return True
            if not self.server.forum_report_limiter.allow("forum_report", self._client_address()):
                self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "600"),))
                return True
            try:
                payload = self._read_json_object(max_bytes=8192)
            except AuthError as exc:
                self._json(400, {"error": str(exc)})
                return True
            allowed = {"reason", "thread_id", "reply_id", "detail"}
            if "reason" not in payload or not set(payload).issubset(allowed):
                self._json(400, {"error": "Ungültige Meldung."})
                return True
            try:
                report = self.server.forum_store.create_report(
                    user, reason=payload["reason"], thread_id=payload.get("thread_id"),
                    reply_id=payload.get("reply_id"), detail=payload.get("detail"),
                )
            except ForumError as exc:
                message = str(exc)
                status = (404 if message == "Ziel wurde nicht gefunden."
                          else 409 if "bereits gemeldet" in message else 400)
                self._json(status, {"error": message})
                return True
            self._json(201, {"ok": True, "report": report})
            return True

        if path.startswith("/api/forum/reports/") and path.endswith("/decide"):
            if self.command != "POST":
                self._json(405, {"error": "method_not_allowed"})
                return True
            report_id = path[len("/api/forum/reports/"):-len("/decide")]
            if not report_id or "/" in report_id:
                self._json(404, {"error": "not_found"})
                return True
            if not self._request_origin_allowed():
                self._json(403, {"error": "request_origin_not_allowed"})
                return True
            user = self.server.auth_store.user_for_token(self._auth_cookie_token())
            if user is None:
                self._json(401, {"error": "authentication_required"})
                return True
            if user.user_id not in forum_moderator_ids():
                self._json(403, {"error": "moderator_required"})
                return True
            if not self.server.forum_moderation_limiter.allow("forum_moderation_decision", self._client_address()):
                self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "600"),))
                return True
            try:
                payload = self._read_json_object(max_bytes=4096)
            except AuthError as exc:
                self._json(400, {"error": str(exc)})
                return True
            allowed = {"decision", "content_action", "note"}
            if "decision" not in payload or not set(payload).issubset(allowed):
                self._json(400, {"error": "Ungültige Moderationsentscheidung."})
                return True
            try:
                result = self.server.forum_store.decide_report(
                    report_id, payload["decision"], user,
                    content_action=payload.get("content_action"), note=payload.get("note"),
                )
            except ForumError as exc:
                self._json(400, {"error": str(exc)})
                return True
            if result is None:
                self._json(404, {"error": "report_not_found"})
                return True
            response = {"ok": True}
            response.update(result)
            self._json(200, response)
            return True

        if path == "/api/forum/notifications":
            if self.command != "GET":
                self._json(405, {"error": "method_not_allowed"})
                return True
            user = self.server.auth_store.user_for_token(self._auth_cookie_token())
            if user is None:
                self._json(401, {"error": "authentication_required"})
                return True
            try:
                notes = self.server.forum_store.list_notifications(user.user_id)
            except ForumError as exc:
                self._json(400, {"error": str(exc)})
                return True
            self._json(200, {"ok": True, "notifications": notes})
            return True

        if path.startswith("/api/forum/notifications/"):
            if self.command != "POST":
                self._json(405, {"error": "method_not_allowed"})
                return True
            if not path.endswith("/read"):
                self._json(404, {"error": "not_found"})
                return True
            notification_id = path[len("/api/forum/notifications/"):-len("/read")]
            if not notification_id or "/" in notification_id:
                self._json(404, {"error": "not_found"})
                return True
            if not self._request_origin_allowed():
                self._json(403, {"error": "request_origin_not_allowed"})
                return True
            user = self.server.auth_store.user_for_token(self._auth_cookie_token())
            if user is None:
                self._json(401, {"error": "authentication_required"})
                return True
            try:
                changed = self.server.forum_store.mark_notification_read(notification_id, user.user_id)
            except ForumError as exc:
                self._json(400, {"error": str(exc)})
                return True
            if not changed:
                self._json(404, {"error": "notification_not_found"})
                return True
            self._json(200, {"ok": True, "notification_id": notification_id})
            return True

        if path.startswith("/api/forum/reports/"):
            if self.command != "POST":
                self._json(405, {"error": "method_not_allowed"})
                return True
            if not path.endswith("/resolve"):
                self._json(404, {"error": "not_found"})
                return True
            report_id = path[len("/api/forum/reports/"):-len("/resolve")]
            if not report_id or "/" in report_id:
                self._json(404, {"error": "not_found"})
                return True
            if not self._request_origin_allowed():
                self._json(403, {"error": "request_origin_not_allowed"})
                return True
            user = self.server.auth_store.user_for_token(self._auth_cookie_token())
            if user is None:
                self._json(401, {"error": "authentication_required"})
                return True
            if user.user_id not in forum_moderator_ids():
                self._json(403, {"error": "moderator_required"})
                return True
            if not self.server.forum_moderation_limiter.allow("forum_moderation_decision", self._client_address()):
                self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "600"),))
                return True
            try:
                payload = self._read_json_object(max_bytes=4096)
            except AuthError as exc:
                self._json(400, {"error": str(exc)})
                return True
            if set(payload) != {"status"}:
                self._json(400, {"error": "Request must contain only status."})
                return True
            try:
                changed = self.server.forum_store.resolve_report(
                    report_id, status=payload["status"], resolver=user,
                )
            except ForumError as exc:
                self._json(400, {"error": str(exc)})
                return True
            if not changed:
                self._json(404, {"error": "report_not_found"})
                return True
            self._json(200, {"ok": True, "report_id": report_id, "status": payload["status"]})
            return True

        if path.startswith("/api/forum/users/"):
            if self.command != "GET":
                self._json(405, {"error": "method_not_allowed"})
                return True
            if not path.endswith("/posts"):
                self._json(404, {"error": "not_found"})
                return True
            user_id = path[len("/api/forum/users/"):-len("/posts")]
            if not user_id or "/" in user_id:
                self._json(404, {"error": "not_found"})
                return True
            user = self.server.auth_store.user_for_token(self._auth_cookie_token())
            if user is None:
                self._json(401, {"error": "authentication_required"})
                return True
            try:
                posts = self.server.forum_store.list_user_posts(user_id)
            except ForumError as exc:
                self._json(400, {"error": str(exc)})
                return True
            self._json(200, {"ok": True, "user_id": user_id, "posts": posts})
            return True

        if path != "/api/forum/threads" and not path.startswith("/api/forum/threads/"):
            return False

        if self.command == "GET":
            if path == "/api/forum/threads":
                threads = self.server.forum_store.list_threads()
                self._json(200, {"ok": True, "threads": threads})
                return True
            thread_id = path[len("/api/forum/threads/"):]
            thread = self.server.forum_store.get_thread(thread_id)
            if thread is None:
                self._json(404, {"error": "thread_not_found"})
            else:
                self._json(200, {"ok": True, "thread": thread})
            return True

        if self.command != "POST":
            self._json(405, {"error": "method_not_allowed"})
            return True

        if not self._request_origin_allowed():
            self._json(403, {"error": "request_origin_not_allowed"})
            return True
        user = self.server.auth_store.user_for_token(self._auth_cookie_token())
        if user is None:
            self._json(401, {"error": "authentication_required"})
            return True

        if path == "/api/forum/threads":
            if not self.server.forum_thread_limiter.allow("forum_thread", self._client_address()):
                self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "600"),))
                return True
            try:
                payload = self._read_json_object(max_bytes=16384)
            except AuthError as exc:
                self._json(400, {"error": str(exc)})
                return True
            if set(payload) != {"title", "body"}:
                self._json(400, {"error": "Request must contain only title and body."})
                return True
            try:
                thread = self.server.forum_store.create_thread(user, payload["title"], payload["body"])
            except ForumError as exc:
                self._json(400, {"error": str(exc)})
                return True
            self._json(201, {"ok": True, "thread": thread})
            return True

        prefix = "/api/forum/threads/"
        if path.startswith(prefix) and path.endswith("/replies"):
            thread_id = path[len(prefix):-len("/replies")]
            if not self.server.forum_reply_limiter.allow("forum_reply", self._client_address()):
                self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "600"),))
                return True
            try:
                payload = self._read_json_object(max_bytes=8192)
            except AuthError as exc:
                self._json(400, {"error": str(exc)})
                return True
            if set(payload) != {"body"}:
                self._json(400, {"error": "Request must contain only body."})
                return True
            try:
                reply = self.server.forum_store.create_reply(user, thread_id, payload["body"])
            except ForumError as exc:
                message = str(exc)
                status = 404 if message == "Thema wurde nicht gefunden." else 423 if "gesperrt" in message else 400
                self._json(status, {"error": message})
                return True
            self._json(201, {"ok": True, "reply": reply})
            return True

        self._json(404, {"error": "not_found"})
        return True

    def _platform_user(self, *, write: bool = False) -> User | None:
        user = self.server.auth_store.user_for_token(self._auth_cookie_token())
        if user is None:
            self._json_with_headers(401, {"error": "authentication_required"})
            return None
        if write and not self._request_origin_allowed() and not self._studio_client_request():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return None
        return user

    def _oauth_provider(self, platform: str) -> OAuthProvider:
        return OAuthProvider(OAuthProviderConfig.from_environment(platform))

    def _oauth_callback_page(self, platform: str, ok: bool, code: str, status: int = 200) -> None:
        payload = json.dumps({
            "type": "streamiov-oauth-callback", "platform": platform,
            "ok": ok, "code": code,
        }).replace("<", "\\u003c")
        headline = "Verbindung eingerichtet" if ok else "Verbindung fehlgeschlagen"
        detail = ("Du kannst dieses Fenster schließen." if ok
                  else f"Fehler: {html.escape(code)}. Es wurden keine Zugangsdaten gespeichert.")
        body = (
            "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>StreamioV-Verbindung</title></head>"
            "<body><h1>" + headline + "</h1><p>" + detail + "</p>"
            "<script>const payload=" + payload + ";"
            "if(window.opener){window.opener.postMessage(payload,location.origin)}"
            "window.close();</script></body></html>"
        )
        self._send_html(status, body)

    def _platform_request(self, path: str, query: dict[str, list[str]]) -> bool:
        prefix = "/api/v1/platforms"
        if path != prefix and not path.startswith(prefix + "/"):
            return False
        if path == prefix:
            if self.command != "GET":
                self._json_with_headers(405, {"error": "method_not_allowed"})
                return True
            user = self._platform_user()
            if user is None:
                return True
            configs = oauth_platform_statuses(self.server.connection_store)
            for platform, info in configs.items():
                info["connection"] = (
                    self.server.connection_store.get_connection_status(user.user_id, platform)
                    if self.server.connection_store else None
                )
            self._json_with_headers(200, {"ok": True, "platforms": configs})
            return True

        parts = path[len(prefix) + 1:].split("/")
        platform = parts[0]
        if platform not in OAUTH_PLATFORMS or len(parts) > 2:
            self._json_with_headers(404, {"error": "platform_not_found"})
            return True
        action = parts[1] if len(parts) == 2 else "status"
        if action == "callback" and self.command == "GET":
            if not self.server.oauth_limiter.allow("oauth_callback", self._client_address()):
                self._oauth_callback_page(platform, False, "too_many_attempts", status=429)
                return True
            error = (query.get("error") or [""])[0]
            state = (query.get("state") or [""])[0]
            code = (query.get("code") or [""])[0]
            if error and len(error) <= 256:
                if state and self.server.connection_store:
                    self.server.connection_store.fail_oauth_state(platform, state, "authorization_denied")
                self._oauth_callback_page(platform, False, "authorization_denied")
                return True
            if (not state or len(state) > 512 or not code or len(code) > 2048
                    or self.server.connection_store is None):
                self._oauth_callback_page(platform, False, "oauth_callback_invalid")
                return True
            try:
                pending = self.server.connection_store.find_pending_oauth_state(platform, state)
            except OAuthConnectionError:
                pending = None
            if pending is None:
                self._oauth_callback_page(platform, False, "oauth_state_invalid_or_expired")
                return True
            try:
                provider = self._oauth_provider(platform)
                tokens = provider.exchange_code(code, code_verifier=pending["code_verifier"])
                self.server.connection_store.save_verified_connection(
                    pending["user_id"], platform, state,
                    tokens["account_id"], tokens.get("account_name"),
                    tokens["access_token"], tokens.get("refresh_token"),
                    tokens["expires_at"], scopes=tokens.get("scopes") or [],
                    metadata={"oauth_environment": provider.config.environment},
                )
            except OAuthProviderError as exc:
                self.server.connection_store.record_oauth_error(pending["user_id"], platform, exc.code)
                self.server.connection_store.clear_oauth_state(pending["user_id"], platform)
                self._oauth_callback_page(platform, False, exc.code)
                return True
            except OAuthConnectionError:
                self._oauth_callback_page(platform, False, "oauth_storage_error")
                return True
            self._oauth_callback_page(platform, True, "connected")
            return True

        user = self._platform_user(write=self.command == "POST")
        if user is None:
            return True
        if self.server.connection_store is None:
            self._json_with_headers(503, {"error": "oauth_storage_unavailable"})
            return True
        config = platform_config_status(platform)
        connection = self.server.connection_store.get_connection_status(user.user_id, platform)

        if action == "status" and self.command == "GET":
            self._json_with_headers(200, {"ok": True, "platform": platform,
                                          "config": config, "connection": connection})
            return True
        if self.command != "POST":
            self._json_with_headers(405, {"error": "method_not_allowed"})
            return True
        if not self.server.oauth_limiter.allow(f"oauth_{action}", self._client_address()):
            self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "600"),))
            return True
        try:
            payload = self._read_json_object(max_bytes=1024)
        except AuthError as exc:
            self._json_with_headers(400, {"error": str(exc)})
            return True
        if payload:
            self._json_with_headers(400, {"error": "Request body must be an empty object."})
            return True

        if action == "connect":
            if not config.get("configured"):
                self._json_with_headers(503, {"error": "oauth_not_configured",
                                              "missing": config.get("missing", [])})
                return True
            try:
                authorization = self._oauth_provider(platform).create_authorization()
                self.server.connection_store.create_oauth_state(
                    user.user_id, platform, authorization["state"],
                    code_verifier=authorization["code_verifier"],
                    redirect_uri=authorization["redirect_uri"],
                    scopes=authorization["scopes"],
                )
            except OAuthProviderError as exc:
                self._json_with_headers(503, {"error": exc.code})
                return True
            except OAuthConnectionError as exc:
                self._json_with_headers(503, {"error": "oauth_state_unavailable", "detail": str(exc)[:120]})
                return True
            self._json_with_headers(200, {
                "ok": True, "platform": platform,
                "authorization_url": authorization["url"],
                "state": authorization["state"],
                "expires_in": authorization["expires_in"],
            })
            return True

        if action == "refresh":
            if not config.get("configured"):
                self._json_with_headers(503, {"error": "oauth_not_configured",
                                              "missing": config.get("missing", [])})
                return True
            with self.server.oauth_refresh_lock:
                try:
                    refresh_token = self.server.connection_store.get_refresh_token(
                        user.user_id, platform
                    )
                except OAuthConnectionError:
                    self._json_with_headers(503, {"error": "oauth_storage_error"})
                    return True
                if not refresh_token:
                    self._json_with_headers(409, {"error": "refresh_token_unavailable"})
                    return True
                try:
                    tokens = self._oauth_provider(platform).refresh(
                        refresh_token, scopes=(connection or {}).get("scopes") or []
                    )
                    self.server.connection_store.update_tokens(
                        user.user_id, platform, tokens["access_token"],
                        refresh_token=tokens.get("refresh_token"),
                        expires_at=tokens["expires_at"], scopes=tokens.get("scopes") or [],
                        expected_refresh_token=refresh_token,
                    )
                except OAuthProviderError as exc:
                    if exc.code in {"invalid_grant", "invalid_client", "unauthorized_client", "access_denied"}:
                        self.server.connection_store.mark_reauthorization_required(
                            user.user_id, platform, exc.code
                        )
                        self._json_with_headers(401, {"error": "reauthorization_required", "code": exc.code})
                    elif exc.retryable:
                        self._json_with_headers(502, {"error": "oauth_provider_unavailable"})
                    else:
                        self._json_with_headers(400, {"error": exc.code})
                    return True
                except OAuthConnectionError as exc:
                    if "already rotated" in str(exc):
                        self._json_with_headers(409, {"error": "refresh_token_rotated"})
                    else:
                        self._json_with_headers(503, {"error": "oauth_storage_error"})
                    return True
            updated = self.server.connection_store.get_connection_status(user.user_id, platform)
            self._json_with_headers(200, {"ok": True, "platform": platform, "status": updated})
            return True

        if action == "disconnect":
            token_to_revoke = None
            if connection and connection.get("connected"):
                stored = self.server.connection_store.get_tokens(user.user_id, platform)
                token_to_revoke = stored[0] if stored else None
            if token_to_revoke is None:
                try:
                    token_to_revoke = self.server.connection_store.get_refresh_token(user.user_id, platform)
                except OAuthConnectionError:
                    token_to_revoke = None
            revoked = True
            revoke_error = None
            if token_to_revoke:
                try:
                    self._oauth_provider(platform).revoke(token_to_revoke)
                except OAuthProviderError as exc:
                    revoked = False
                    revoke_error = exc.code
            self.server.connection_store.disconnect_platform(user.user_id, platform)
            self._json_with_headers(200, {
                "ok": True, "platform": platform,
                "status": self.server.connection_store.get_connection_status(user.user_id, platform),
                "revoked": revoked, "revoke_error": revoke_error,
            })
            return True

        self._json_with_headers(404, {"error": "platform_action_not_found"})
        return True

    def _wishbox_authorized(self) -> str | None:
        user = self.server.auth_store.user_for_token(self._auth_cookie_token())
        if user is None:
            self._json_with_headers(401, {"error": "authentication_required"})
            return None
        if self.headers.get("X-Streamiov-Client") != "studio":
            self._json_with_headers(403, {"error": "studio_client_header_required"})
            return None
        if self.headers.get("Origin") and not self._request_origin_allowed():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return None
        if not self.headers.get("Origin") and not self._studio_client_request():
            self._json_with_headers(403, {"error": "request_origin_not_allowed"})
            return None
        if not self.server.wishbox_limiter.allow("wishbox", self._client_address()):
            self._json_with_headers(429, {"error": "too_many_attempts"}, (("Retry-After", "60"),))
            return None
        return user.user_id

    def _wishbox_request(self, path: str, query: dict[str, list[str]]) -> bool:
        prefix = "/api/v1/wishbox/"
        if not path.startswith(prefix):
            return False
        if self.command not in {"GET", "POST"}:
            self._method_not_allowed()
            return True
        user_id = self._wishbox_authorized()
        if user_id is None:
            return True
        tail = path[len(prefix):]
        parts = [part for part in tail.split("/") if part]
        if len(parts) > 3:
            self._json_with_headers(404, {"error": "wishbox_route_not_found"})
            return True
        store = self.server.wishbox_store
        if self.command == "GET":
            if parts == ["handoffs"]:
                self._json_with_headers(200, {"ok": True, "handoffs": store.handoffs(user_id)})
                return True
            if len(parts) == 2 and parts[0] == "orders":
                detail = store.detail(parts[1], user_id)
                if detail is None:
                    self._json_with_headers(404, {"error": "order_not_found"})
                    return True
                self._json_with_headers(200, {"ok": True, "order": detail})
                return True
            if parts == ["orders"]:
                raw_limit = (query.get("limit") or ["50"])[0]
                raw_kind = (query.get("kind") or [None])[0]
                try:
                    limit = int(raw_limit)
                except (TypeError, ValueError):
                    limit = 50
                orders = store.list_orders(user_id, limit=limit, kind=raw_kind)
                self._json_with_headers(200, {"ok": True, "orders": orders})
                return True
            self._json_with_headers(404, {"error": "wishbox_route_not_found"})
            return True
        if parts == ["orders"]:
            try:
                payload = self._read_json_object(max_bytes=4096)
            except AuthError as exc:
                self._json_with_headers(400, {"error": str(exc)})
                return True
            allowed = {"text", "sender", "source", "territory", "priority"}
            if not set(payload).issubset(allowed) or "text" not in payload:
                self._json_with_headers(400, {"error": "invalid_order_request"})
                return True
            try:
                order = store.submit(user_id, payload["text"], **{
                    key: value for key, value in payload.items() if key != "text"
                })
            except WishboxError as exc:
                self._json_with_headers(400, {"error": str(exc)})
                return True
            self._json_with_headers(200 if order.get("duplicate") else 201,
                                    {"ok": True, "order": order})
            return True
        if len(parts) == 3 and parts[0] == "orders":
            action = parts[2]
            actions = {"dispatch": set(), "claim": {"agent"}, "reject": {"reason"},
                       "clarify": {"answer"}, "complete": {"result", "agent"}}
            if action not in actions:
                self._json_with_headers(404, {"error": "wishbox_action_not_found"})
                return True
            try:
                payload = self._read_json_object(max_bytes=4096)
            except AuthError as exc:
                self._json_with_headers(400, {"error": str(exc)})
                return True
            if not set(payload).issubset(actions[action]):
                self._json_with_headers(400, {"error": "invalid_action_request"})
                return True
            try:
                if action == "dispatch":
                    order = store.dispatch(parts[1], user_id)
                elif action == "claim":
                    order = store.claim(parts[1], user_id, agent=payload.get("agent", "gaming"))
                elif action == "reject":
                    order = store.reject(parts[1], user_id, reason=payload.get("reason", ""))
                elif action == "clarify":
                    order = store.clarify(parts[1], user_id, answer=payload.get("answer", ""))
                else:
                    order = store.complete(parts[1], user_id, payload.get("result", ""),
                                           agent=payload.get("agent", "gaming"))
            except WishboxError as exc:
                status = 404 if str(exc) == "Auftrag nicht gefunden." else 400
                self._json_with_headers(status, {"error": str(exc)})
                return True
            self._json_with_headers(200, {"ok": True, "order": order})
            return True
        self._json_with_headers(404, {"error": "wishbox_route_not_found"})
        return True

    def _ai_tasks_request(self, path: str) -> bool:
        if self.command != "GET":
            return False
        if path != "/api/v1/ai/tasks" and not path.startswith("/api/v1/ai/tasks/"):
            return False
        user = self.server.auth_store.user_for_token(self._auth_cookie_token())
        if user is None:
            self._json_with_headers(401, {"error": "authentication_required"})
            return True
        if self.headers.get("X-Streamiov-Client") != "studio":
            self._json_with_headers(403, {"error": "studio_client_header_required"})
            return True
        if path == "/api/v1/ai/tasks":
            tasks = self.server.ai_task_store.list(user.user_id)
            self._json_with_headers(200, {"ok": True, "tasks": tasks})
            return True
        task_id = path[len("/api/v1/ai/tasks/"):]
        if not task_id or "/" in task_id:
            self._json_with_headers(404, {"error": "task_not_found"})
            return True
        task = self.server.ai_task_store.get(task_id, user.user_id)
        if task is None:
            self._json_with_headers(404, {"error": "task_not_found"})
            return True
        self._json_with_headers(200, {"ok": True, "task": task})
        return True

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=8)
        if self._auth_request(path):
            return
        if self._platform_request(path, query):
            return
        if self._catalog_request(path):
            return
        if self._music_state_request(path, query):
            return
        if self._music_request(path, query):
            return
        if self._forum_request(path, query):
            return
        if self._ai_tasks_request(path):
            return
        if self._wishbox_request(path, query):
            return
        if self._events_request(path, query):
            return
        if path == "/healthz":
            checks = database_health(self.server.data_dir)
            self._json(200 if checks["ok"] else 503, {
                "status": "ok" if checks["ok"] else "degraded",
                "service": "streamiov-host",
                "version": VERSION,
                "uptime_seconds": max(0, int(time.monotonic() - STARTED_AT)),
                "stores": checks["stores"],
            })
            return
        if path == "/api/v1/status":
            checks = database_health(self.server.data_dir)
            accounts_ok = checks["stores"]["accounts"]["ok"]
            forum_ok = checks["stores"]["forum"]["ok"]
            catalog_ok = checks["stores"]["catalog"]["ok"]
            ai_tasks_ok = checks["stores"]["ai_tasks"]["ok"]
            events_ok = checks["stores"]["events"]["ok"]
            music_state_ok = checks["stores"]["music_state"]["ok"]
            wishbox_ok = checks["stores"]["wishbox"]["ok"]
            try:
                events_count = self.server.event_store.count_all() if events_ok else 0
            except (OSError, sqlite3.Error):
                events_count = 0
                events_ok = False
            data_summary = self.server.data_store.summary()
            self._json(200, {
                "service": "streamiov-host",
                "version": VERSION,
                "stage": "local-account-api",
                "api_ready": False,
                "auth_ready": accounts_ok,
                "account_api_ready": accounts_ok,
                "registration_open": self.server.registration_open,
                "catalog_ready": catalog_ok and bool(data_summary["ok"]),
                "catalog_read_only": True,
                "catalog_counts": data_summary["counts"],
                "forum_ready": forum_ok,
                "forum_read_only": False,
                "forum_writes_require_session": True,
                "forum_reports_enabled": forum_ok,
                "forum_moderation_enabled": forum_ok and bool(forum_moderator_ids()),
                "forum_moderation_actions_enabled": forum_ok,
                "forum_notifications_enabled": False,
                "forum_spam_signals_enabled": forum_ok,
                "forum_history_requires_session": True,
                "stores": checks["stores"],
                "data_store": {
                    "ok": catalog_ok and bool(data_summary["ok"]),
                    "read_only": True,
                    "schema_version": data_summary["schema_version"],
                    "seeded_at": data_summary["seeded_at"],
                    "counts": data_summary["counts"],
                    "errors": data_summary["errors"],
                    "legacy_databases_read": False,
                },
                "ai_execution_ready": bool(local_ai_status().get("ready")),
                "ai_task_endpoint_ready": True,
                "ai_tasks_ready": ai_tasks_ok,
                "event_ledger_ready": events_ok,
                "event_schema_version": EVENT_SCHEMA_VERSION,
                "event_count": events_count,
                "music_state_ready": music_state_ok,
                "music_state_requires_session": True,
                "music_gate": self.server.music_catalog.status(),
                "wishbox_ready": wishbox_ok and self.server.music_catalog.library is not None,
                "wishbox_endpoint_ready": True,
                "wishbox_requires_session": True,
                "wishbox_music_orders_require_live_rights": True,
                "platform_connections_ready": self.server.connection_store is not None,
                "platform_configs": oauth_platform_statuses(self.server.connection_store),
                 "platform_integrations_ready": oauth_ready(self.server.connection_store),
                 "shared_rate_limiter": getattr(self.server, "shared_rate_limit_status", None),
             })
            return
        if path == "/api/v1/ai/status":
            self._json(200, local_ai_status())
            return
        target = resolve_public_file(self.server.site_root, self.path)
        if target is None:
            self._json(404, {"error": "not_found"})
            return
        try:
            body = target.read_bytes()
        except OSError:
            self._json(404, {"error": "not_found"})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        self._send_bytes(200, body, content_type, cache="no-cache")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=8)
        if self._wishbox_request(path, query):
            return
        if self._platform_request(path, {}):
            return
        if path == "/api/v1/ai/tasks":
            self._ai_task_request()
            return
        if self._music_state_request(path, {}):
            return
        if self._events_request(path, {}):
            return
        if self._forum_request(path, {}):
            return
        if self._auth_request(path):
            return
        self._json(405, {"error": "method_not_allowed"})

    def _method_not_allowed(self) -> None:
        self._json_with_headers(405, {"error": "method_not_allowed"},
                                (("Allow", "GET, HEAD, POST"),))

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve StreamioV's static site and host status locally.")
    parser.add_argument("--host", default=os.environ.get("STREAMIOV_HOST_BIND", "127.0.0.1"),
                        help="Bind address (default: 127.0.0.1; public deployment is not ready).")
    parser.add_argument("--port", type=int, default=int(os.environ.get("STREAMIOV_HOST_PORT", "8765")))
    parser.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT)
    parser.add_argument("--data-dir", type=Path,
                        default=Path(os.environ.get("STREAMIOV_DATA_DIR", "~/.local/share/streamiov-host")).expanduser())
    parser.add_argument("--raw-data-root", type=Path,
                        default=Path(os.environ.get("STREAMIOV_RAW_DATA_ROOT", str(DEFAULT_RAW_DATA_ROOT))).expanduser(),
                        help="Repository JSON raw-data root used to seed the read-only catalog.")
    parser.add_argument("--music-root", type=Path,
                        default=(Path(os.environ["STREAMIOV_MUSIC_ROOT"]).expanduser()
                                 if os.environ.get("STREAMIOV_MUSIC_ROOT") else None),
                        help="Local directory containing rights-approved audio files; defaults to DATA_DIR/music.")
    parser.add_argument("--tls-cert", help="TLS certificate PEM file (required for non-loopback binds).")
    parser.add_argument("--tls-key", help="TLS private key PEM file (required for non-loopback binds).")
    parser.add_argument("--trust-loopback-proxy", action="store_true",
                        help="Trust X-Forwarded-Proto=https only from a loopback peer (for a local TLS proxy).")
    parser.add_argument("--reset-password", metavar="USERNAME",
                        help="Interactively reset a local account password and revoke its sessions; does not start the server.")
    parser.add_argument("--create-account", metavar="USERNAME",
                        help="Create the first/local account interactively; requires an owner terminal and does not start the server.")
    parser.add_argument("--enable-registration", action="store_true",
                        help="Enable web self-registration (keep off until remote host security review is complete).")
    parser.add_argument("--generate-oauth-key", action="store_true",
                        help="Create a private token encryption key in DATA_DIR; does not start the server.")
    parser.add_argument("--backup-create", action="store_true",
                        help="Create a verified local Core backup; does not start the server.")
    parser.add_argument("--backup-list", action="store_true",
                        help="List verified local Core backups; does not start the server.")
    parser.add_argument("--backup-prune", action="store_true",
                        help="Delete old verified backups beyond --backup-keep; does not start the server.")
    parser.add_argument("--backup-keep", type=int, default=3,
                        help="Number of newest verified backups to retain with --backup-prune (default: 3).")
    parser.add_argument("--backup-verify", metavar="BACKUP_DIR",
                        help="Verify one local Core backup; does not start the server.")
    parser.add_argument("--backup-restore", metavar="BACKUP_DIR",
                        help="Restore one verified backup into DATA_DIR; does not start the server.")
    parser.add_argument("--backup-force", action="store_true",
                        help="Allow --backup-restore to replace existing Core files.")
    parser.add_argument("--backup-dir", metavar="DIR",
                        help="Backup output/list root; defaults to DATA_DIR/backups.")
    parser.add_argument("--backup-schedule-status", action="store_true",
                        help="Show the local backup schedule state; does not start the server.")
    parser.add_argument("--backup-schedule-run", action="store_true",
                        help="Run one local backup, verification and prune cycle; does not start the server.")
    parser.add_argument("--backup-policy", metavar="FILE",
                        help="Local backup schedule policy file for status, schedule-run, or server start.")
    parser.add_argument("--forum-list", action="store_true",
                        help="List recent forum threads and replies for moderation; does not start the server.")
    parser.add_argument("--forum-lock", metavar="THREAD_ID",
                        help="Lock a forum thread; does not start the server.")
    parser.add_argument("--forum-unlock", metavar="THREAD_ID",
                        help="Unlock a forum thread; does not start the server.")
    parser.add_argument("--forum-delete-thread", metavar="THREAD_ID",
                        help="Soft-delete a forum thread; does not start the server.")
    parser.add_argument("--forum-delete-reply", metavar="REPLY_ID",
                        help="Soft-delete a forum reply; does not start the server.")
    parser.add_argument("--forum-reports", action="store_true",
                        help="List forum abuse reports as JSON lines; does not start the server.")
    parser.add_argument("--forum-resolve-report", nargs=2, metavar=("REPORT_ID", "STATUS"),
                        help="Resolve or dismiss an open forum report; does not start the server.")
    parser.add_argument("--forum-decide-report", nargs=2, metavar=("REPORT_ID", "DECISION"),
                        help="Decide an open forum report with an optional content action; does not start the server.")
    parser.add_argument("--forum-content-action", choices=sorted({"none", "delete", "lock", "unlock"}),
                        help="Content action for --forum-decide-report.")
    parser.add_argument("--forum-note", help="Moderator note for --forum-decide-report.")
    parser.add_argument("--forum-notifications", metavar="USER_ID",
                        help="List a user's moderation notifications as JSON lines; does not start the server.")
    parser.add_argument("--forum-mark-notification-read", nargs=2, metavar=("NOTIFICATION_ID", "USER_ID"),
                        help="Mark a moderation notification as read; does not start the server.")
    parser.add_argument("--forum-spam", action="store_true",
                        help="List visible posts with advisory spam flags as JSON lines; does not start the server.")
    parser.add_argument("--forum-history", metavar="USER_ID",
                        help="List a user's visible forum posts as JSON lines; does not start the server.")
    parser.add_argument("--forum-retention-status", action="store_true",
                        help="Report the forum retention policy and eligible records without deleting anything.")
    parser.add_argument("--forum-retention-run", action="store_true",
                        help="Apply the local forum retention policy; does not start the server.")
    parser.add_argument("--forum-retention-schedule-status", action="store_true",
                        help="Show the local forum retention schedule state; does not start the server.")
    parser.add_argument("--forum-retention-schedule-run", action="store_true",
                        help="Run one local forum retention cycle; does not start the server.")
    parser.add_argument("--forum-retention-policy", metavar="FILE",
                        help="Local forum retention schedule policy file for status, schedule-run, or server start.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    forum_actions = [
        args.forum_list, args.forum_lock, args.forum_unlock,
        args.forum_delete_thread, args.forum_delete_reply,
        args.forum_reports, args.forum_resolve_report, args.forum_decide_report,
        args.forum_notifications, args.forum_mark_notification_read,
        args.forum_spam, args.forum_history,
        args.forum_retention_status, args.forum_retention_run,
        args.forum_retention_schedule_status, args.forum_retention_schedule_run,
    ]
    backup_actions = [args.backup_create, args.backup_list, args.backup_prune,
                      args.backup_verify, args.backup_restore,
                      args.backup_schedule_status, args.backup_schedule_run]
    if any(backup_actions):
        if sum(1 for action in backup_actions if action) != 1:
            raise SystemExit("Choose exactly one backup maintenance action.")
        if args.backup_force and not args.backup_restore:
            raise SystemExit("--backup-force requires --backup-restore.")
        if args.backup_dir and not (args.backup_create or args.backup_list or args.backup_prune):
            raise SystemExit("--backup-dir is only valid with --backup-create, --backup-list, or --backup-prune.")
        if args.backup_keep != 3 and not args.backup_prune:
            raise SystemExit("--backup-keep is only valid with --backup-prune.")
        if args.generate_oauth_key or args.reset_password or args.create_account or any(forum_actions):
            raise SystemExit("Backup maintenance cannot be combined with other maintenance actions.")
        try:
            if args.backup_create:
                backup_root = Path(args.backup_dir).expanduser() if args.backup_dir else None
                print(json.dumps(create_backup(args.data_dir, backup_root), ensure_ascii=False))
            elif args.backup_list:
                backup_root = (Path(args.backup_dir).expanduser() if args.backup_dir
                               else Path(args.data_dir).expanduser() / "backups")
                for entry in list_backups(backup_root):
                    print(json.dumps(entry, ensure_ascii=False))
            elif args.backup_prune:
                backup_root = (Path(args.backup_dir).expanduser() if args.backup_dir
                               else Path(args.data_dir).expanduser() / "backups")
                print(json.dumps(prune_backups(backup_root, args.backup_keep), ensure_ascii=False))
            elif args.backup_schedule_status:
                scheduler = BackupScheduler(args.data_dir, policy_path=args.backup_policy)
                print(json.dumps(scheduler.status(), ensure_ascii=False))
            elif args.backup_schedule_run:
                scheduler = BackupScheduler(args.data_dir, policy_path=args.backup_policy)
                print(json.dumps(scheduler.run_once(force=True), ensure_ascii=False))
            elif args.backup_verify:
                print(json.dumps(verify_backup(Path(args.backup_verify).expanduser()), ensure_ascii=False))
            else:
                report = restore_backup(Path(args.backup_restore).expanduser(), args.data_dir,
                                        force=args.backup_force)
                print(json.dumps(report, ensure_ascii=False))
        except BackupError as exc:
            raise SystemExit(str(exc)) from exc
        return 0
    if args.generate_oauth_key:
        if (args.reset_password or args.create_account or any(forum_actions)):
            raise SystemExit("OAuth key generation cannot be combined with other maintenance actions.")
        data_dir = args.data_dir.expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(data_dir, 0o700)
        except OSError:
            pass
        key_path = data_dir / "oauth-token.key"
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise SystemExit(f"Token key already exists: {key_path}") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as key_file:
            key_file.write(secrets.token_urlsafe(48) + "\n")
        os.chmod(key_path, 0o600)
        print(f"OAuth token encryption key created: {key_path}")
        return 0
    if args.reset_password and args.create_account:
        raise SystemExit("Choose either --reset-password or --create-account.")
    if any(forum_actions) and (args.reset_password or args.create_account):
        raise SystemExit("Forum moderation cannot be combined with account maintenance.")
    if args.reset_password or args.create_account:
        if not sys.stdin.isatty():
            raise SystemExit("Account create/reset requires an interactive local terminal.")
        new_password = getpass.getpass("New password (at least 12 characters): ")
        confirmation = getpass.getpass("Repeat new password: ")
        if new_password != confirmation:
            raise SystemExit("Passwords did not match; no change made.")
        try:
            store = AuthStore(args.data_dir)
            if args.create_account:
                user, token = store.register(args.create_account, new_password)
                store.revoke(token)
                print(f"Local account created: {user.username}")
                return 0
            updated = store.reset_password(args.reset_password, new_password)
        except AuthError as exc:
            raise SystemExit(str(exc)) from exc
        if not updated:
            raise SystemExit("Account not found; no change made.")
        print("Password updated; all existing sessions were revoked.")
        return 0
    if (args.forum_content_action is not None or args.forum_note is not None) and not args.forum_decide_report:
        raise SystemExit("--forum-content-action and --forum-note require --forum-decide-report.")
    if any(forum_actions):
        if sum(1 for action in forum_actions if action) != 1:
            raise SystemExit("Choose exactly one forum moderation action.")
        if args.forum_retention_schedule_status:
            scheduler = ForumRetentionScheduler(args.data_dir, policy_path=args.forum_retention_policy)
            print(json.dumps(scheduler.status(), ensure_ascii=False))
            return 0
        if args.forum_retention_schedule_run:
            scheduler = ForumRetentionScheduler(args.data_dir, policy_path=args.forum_retention_policy)
            print(json.dumps(scheduler.run_once(force=True), ensure_ascii=False))
            return 0
        store = ForumStore(args.data_dir)
        if args.forum_retention_status:
            print(json.dumps(store.retention_status(), ensure_ascii=False))
            return 0
        if args.forum_retention_run:
            print(json.dumps(store.apply_retention(), ensure_ascii=False))
            return 0
        if args.forum_list:
            for item in store.moderation_snapshot():
                print(json.dumps(item, ensure_ascii=False))
            return 0
        if args.forum_reports:
            for item in store.list_reports(status="all"):
                print(json.dumps(item, ensure_ascii=False))
            return 0
        if args.forum_resolve_report:
            report_id, status = args.forum_resolve_report
            operator = User(user_id="cli-operator", username="operator", created_at=0)
            try:
                changed = store.resolve_report(report_id, status=status, resolver=operator)
            except ForumError as exc:
                raise SystemExit(str(exc)) from exc
            if not changed:
                raise SystemExit("Forum report not found or already resolved; no change made.")
            print(json.dumps({
                "ok": True, "report_id": report_id, "status": status,
                "resolver": operator.user_id,
            }, ensure_ascii=False))
            return 0
        if args.forum_decide_report:
            report_id, decision = args.forum_decide_report
            operator = User(user_id="cli-operator", username="operator", created_at=0)
            try:
                result = store.decide_report(
                    report_id, decision, operator,
                    content_action=args.forum_content_action, note=args.forum_note,
                )
            except ForumError as exc:
                raise SystemExit(str(exc)) from exc
            if result is None:
                raise SystemExit("Forum report not found or already decided; no change made.")
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.forum_notifications:
            try:
                notes = store.list_notifications(args.forum_notifications)
            except ForumError as exc:
                raise SystemExit(str(exc)) from exc
            for item in notes:
                print(json.dumps(item, ensure_ascii=False))
            return 0
        if args.forum_mark_notification_read:
            notification_id, user_id = args.forum_mark_notification_read
            try:
                changed = store.mark_notification_read(notification_id, user_id)
            except ForumError as exc:
                raise SystemExit(str(exc)) from exc
            if not changed:
                raise SystemExit("Forum notification not found for this user; no change made.")
            print(json.dumps({
                "ok": True, "notification_id": notification_id, "user_id": user_id,
            }, ensure_ascii=False))
            return 0
        if args.forum_spam:
            for item in store.spam_snapshot():
                print(json.dumps(item, ensure_ascii=False))
            return 0
        if args.forum_history:
            try:
                posts = store.list_user_posts(args.forum_history)
            except ForumError as exc:
                raise SystemExit(str(exc)) from exc
            for item in posts:
                print(json.dumps(item, ensure_ascii=False))
            return 0
        if args.forum_lock:
            changed = store.set_locked(args.forum_lock, True)
            action = "locked"
        elif args.forum_unlock:
            changed = store.set_locked(args.forum_unlock, False)
            action = "unlocked"
        elif args.forum_delete_thread:
            changed = store.delete_thread(args.forum_delete_thread)
            action = "deleted"
        else:
            changed = store.delete_reply(args.forum_delete_reply)
            action = "deleted"
        if not changed:
            raise SystemExit("Forum entry not found or already changed; no change made.")
        print(f"Forum entry {action}.")
        return 0
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Port must be between 1024 and 65535.")
    try:
        use_tls = validate_tls_settings(args.host, args.tls_cert, args.tls_key)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.trust_loopback_proxy and args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("--trust-loopback-proxy requires a loopback bind address.")
    if not args.site_root.is_dir():
        raise SystemExit(f"Static site directory does not exist: {args.site_root}")
    try:
        server = StreamioVHTTPServer((args.host, args.port), Handler, args.site_root, args.data_dir,
                                     tls_enabled=use_tls, trust_loopback_proxy=args.trust_loopback_proxy,
                                     registration_open=args.enable_registration,
                                     raw_data_root=args.raw_data_root, music_root=args.music_root)
    except SharedRateLimiterError as exc:
        raise SystemExit(str(exc)) from exc
    scheme = "https" if use_tls else "http"
    if use_tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=args.tls_cert, keyfile=args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scheduler = BackupScheduler(args.data_dir, policy_path=args.backup_policy)
    scheduler_started = scheduler.start()
    retention = ForumRetentionScheduler(args.data_dir, policy_path=args.forum_retention_policy)
    retention_started = retention.start()
    print(f"StreamioV host {VERSION} serving {server.site_root} at {scheme}://{args.host}:{server.server_port}")
    print("Local Core backup schedule: " + ("enabled" if scheduler_started else "disabled") +
          "; backups stay local and production restore remains unverified.")
    print("Local forum retention schedule: " + ("enabled" if retention_started else "disabled") +
          "; automatic deletion requires owner and legal approval.")
    print("Stage: local account API enabled; web registration is " +
          ("open" if server.registration_open else "closed") +
          "; read-only raw-data catalog enabled; AI tasks enabled when a local model is ready; " +
          ("OAuth platform connections enabled" if oauth_ready(server.connection_store)
           else "OAuth platform connections await provider credentials and a token encryption key") + ".")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping StreamioV host.")
    finally:
        retention.stop()
        scheduler.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
