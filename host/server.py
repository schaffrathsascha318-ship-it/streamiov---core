#!/usr/bin/env python3
"""Self-hosted StreamioV homepage and local-account host (standard library only).

This staged host serves static files, local accounts, and non-sensitive health.
It deliberately does not expose OAuth, AI execution, or arbitrary write APIs.
"""
from __future__ import annotations

import argparse
import getpass
import json
import mimetypes
import os
from pathlib import Path
import ipaddress
import ssl
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import unquote, urlsplit


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
STARTED_AT = time.monotonic()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from host.auth import AuthError, AuthStore, RequestRateLimiter
from host.data_store import DataStore


def local_ai_status() -> dict:
    """Report local inference readiness only; this route never runs a task."""
    from ai.providers.local_http import (
        LocalOpenAICompatibleProvider,
        OllamaProvider,
        ProviderError,
    )

    kind = os.environ.get("STREAMIOV_MODEL_PROVIDER", "ollama").lower()
    model = os.environ.get("STREAMIOV_MODEL", "qwen2.5-coder:7b")
    url = os.environ.get("STREAMIOV_MODEL_URL")
    try:
        if kind == "ollama":
            provider = OllamaProvider(model, url or "http://127.0.0.1:11434")
        elif kind == "openai-compatible-local":
            provider = LocalOpenAICompatibleProvider(model, url or "http://127.0.0.1:8000/v1")
        else:
            return {
                "provider": kind,
                "model": model,
                "ready": False,
                "detail": "Host AI status accepts local providers only; no cloud fallback is used.",
            }
        result = provider.check_ready()
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
            "detail": f"Local model status unavailable: {type(exc).__name__}.",
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
                 registration_open: bool = False, raw_data_root: Path | None = None):
        self.site_root = site_root.resolve()
        self.auth_store = AuthStore(data_dir)
        self.data_store = DataStore(data_dir, raw_data_root)
        self.auth_limiter = RequestRateLimiter()
        self.auth_work_slots = threading.BoundedSemaphore(4)
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

    def _send_bytes(self, status: int, body: bytes, content_type: str, *, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
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
                    "id": user.user_id, "username": user.username, "created_at": user.created_at
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
        """Authenticated placeholder for the Studio AI bridge.

        The host intentionally has no task executor yet. This route validates
        the real desktop contract (session cookie + explicit client header) and
        returns a clear "not ready" response instead of a misleading 404 or a
        silent success.
        """
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
            self._read_ai_request()
        except AuthError as exc:
            self._json_with_headers(400, {"error": str(exc)})
            return
        self._json_with_headers(503, {
            "error": "ai_execution_not_ready",
            "detail": (
                "Der lokale Host hat noch keinen KI-Ausführer. "
                "Der Auftrag wurde nicht gespeichert oder ausgeführt."
            ),
            "ai_execution_ready": False,
        })

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

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if self._auth_request(path):
            return
        if self._catalog_request(path):
            return
        if path == "/healthz":
            self._json(200, {
                "status": "ok",
                "service": "streamiov-host",
                "version": VERSION,
                "uptime_seconds": max(0, int(time.monotonic() - STARTED_AT)),
            })
            return
        if path == "/api/v1/status":
            data_summary = self.server.data_store.summary()
            self._json(200, {
                "service": "streamiov-host",
                "version": VERSION,
                "stage": "local-account-api",
                "api_ready": False,
                "auth_ready": True,
                "account_api_ready": True,
                "registration_open": self.server.registration_open,
                "catalog_ready": data_summary["ok"],
                "catalog_read_only": True,
                "catalog_counts": data_summary["counts"],
                "data_store": {
                    "ok": data_summary["ok"],
                    "read_only": True,
                    "schema_version": data_summary["schema_version"],
                    "seeded_at": data_summary["seeded_at"],
                    "counts": data_summary["counts"],
                    "errors": data_summary["errors"],
                    "legacy_databases_read": False,
                },
                "ai_execution_ready": False,
                "ai_task_endpoint_ready": False,
                "platform_integrations_ready": False,
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
        if path == "/api/v1/ai/tasks":
            self._ai_task_request()
            return
        if self._auth_request(path):
            return
        self._json(405, {"error": "method_not_allowed"})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.reset_password and args.create_account:
        raise SystemExit("Choose either --reset-password or --create-account.")
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
    server = StreamioVHTTPServer((args.host, args.port), Handler, args.site_root, args.data_dir,
                                 tls_enabled=use_tls, trust_loopback_proxy=args.trust_loopback_proxy,
                                 registration_open=args.enable_registration,
                                 raw_data_root=args.raw_data_root)
    scheme = "https" if use_tls else "http"
    if use_tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=args.tls_cert, keyfile=args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"StreamioV host {VERSION} serving {server.site_root} at {scheme}://{args.host}:{server.server_port}")
    print("Stage: local account API enabled; web registration is " +
          ("open" if server.registration_open else "closed") +
          "; read-only raw-data catalog enabled; AI tasks and platform integrations remain disabled.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping StreamioV host.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
