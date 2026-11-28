"""Real HTTP tests for Core OAuth connections against a local fake provider."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from host.server import Handler, StreamioVHTTPServer
from services.oauth.connection_service import ConnectionStore
from services.oauth.token_crypto import TokenCrypto


class FakeProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fields(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        return {key: values[0] for key, values in
                parse_qs(self.rfile.read(length).decode("ascii"), keep_blank_values=True).items()}

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        platform = (query.get("platform") or ["tiktok"])[0]
        if parts.path == "/authorize":
            self._json(200, {"ok": True})
            return
        if parts.path == "/identity" and platform == "tiktok":
            self._json(200, {"data": {"user": {
                "open_id": "creator-tiktok", "display_name": "Creator TikTok",
            }}})
            return
        if parts.path == "/identity" and platform == "twitch":
            self._json(200, {
                "client_id": os.environ.get("STREAMIOV_TWITCH_CLIENT_ID", ""),
                "user_id": "creator-twitch", "login": "creator_twitch",
                "scope": ["channel:read:stream_key"],
            })
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parts = urlsplit(self.path)
        fields = self._fields()
        if parts.path == "/token":
            self._token(fields)
            return
        if parts.path == "/revoke":
            self.server.revokes.append(fields.get("token", ""))
            if "revoke-fail" in fields.get("token", ""):
                self._json(500, {"error": "server_error"})
            else:
                self._json(200, {"revoked": True})
            return
        self._json(404, {"error": "not_found"})

    def _token(self, fields: dict[str, str]) -> None:
        grant = fields.get("grant_type")
        if grant == "authorization_code":
            code = fields.get("code", "")
            self.server.codes.append(dict(fields))
            if code == "code-tiktok":
                self._json(200, {
                    "access_token": "access-tiktok", "refresh_token": "refresh-tiktok",
                    "expires_in": 3600, "token_type": "Bearer", "scope": "user.info.basic",
                    "open_id": "creator-tiktok",
                })
                return
            if code == "code-twitch":
                self._json(200, {
                    "access_token": "access-twitch", "refresh_token": "refresh-twitch",
                    "expires_in": 3600, "token_type": "bearer",
                    "scope": ["channel:read:stream_key"],
                })
                return
            if code == "code-bad-refresh":
                self._json(200, {
                    "access_token": "access-tiktok", "refresh_token": "refresh-bad",
                    "expires_in": 3600, "scope": "user.info.basic",
                    "open_id": "creator-tiktok",
                })
                return
            if code == "code-revoke-fail":
                self._json(200, {
                    "access_token": "access-revoke-fail", "refresh_token": "refresh-revoke-fail",
                    "expires_in": 3600, "scope": "user.info.basic",
                    "open_id": "creator-tiktok",
                })
                return
            self._json(400, {"error": "invalid_grant"})
            return
        if grant == "refresh_token":
            refresh = fields.get("refresh_token", "")
            self.server.refreshes.append(dict(fields))
            if refresh.startswith("refresh-bad"):
                self._json(400, {"error": "invalid_grant"})
                return
            self.server.rotation += 1
            self._json(200, {
                "access_token": f"access-rotated-{self.server.rotation}",
                "refresh_token": f"refresh-rotated-{self.server.rotation}",
                "expires_in": 7200, "scope": "user.info.basic",
            })
            return
        self._json(400, {"error": "unsupported_grant_type"})


class PlatformOAuthHttpTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._directory.name) / "host-data"
        self.config_dir = Path(self._directory.name) / "config"
        self.provider = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
        self.provider.codes = []
        self.provider.refreshes = []
        self.provider.revokes = []
        self.provider.rotation = 0
        self.provider_thread = threading.Thread(target=self.provider.serve_forever,
                                                kwargs={"poll_interval": 0.1}, daemon=True)
        self.provider_thread.start()
        self.base = f"http://127.0.0.1:{self.provider.server_port}"
        self._write_configs()
        self.environment = patch.dict(os.environ, {
            "STREAMIOV_TOKEN_KEY": "http-test-token-key-0123456789",
            "STREAMIOV_PLATFORM_CONFIG_DIR": str(self.config_dir),
            "STREAMIOV_PLATFORM_ENV": "sandbox",
            "STREAMIOV_TIKTOK_SANDBOX_CLIENT_KEY": "tiktok-client",
            "STREAMIOV_TIKTOK_SANDBOX_CLIENT_SECRET": "tiktok-secret",
            "STREAMIOV_TIKTOK_SANDBOX_REDIRECT_URI": "http://127.0.0.1:1/api/v1/platforms/tiktok/callback",
            "STREAMIOV_TWITCH_CLIENT_ID": "twitch-client",
            "STREAMIOV_TWITCH_CLIENT_SECRET": "twitch-secret",
            "STREAMIOV_TWITCH_REDIRECT_URI": "http://127.0.0.1:1/api/v1/platforms/twitch/callback",
        })
        self.environment.start()
        self.host = None
        self.host_thread = None
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self._start_host()

    def tearDown(self):
        if self.host is not None:
            self.host.shutdown()
            self.host.server_close()
        if self.host_thread is not None:
            self.host_thread.join(timeout=3)
        self.provider.shutdown()
        self.provider.server_close()
        self.provider_thread.join(timeout=3)
        self.environment.stop()
        self._directory.cleanup()

    def _write_configs(self):
        tiktok = self.config_dir / "tiktok" / "oauth.json"
        twitch = self.config_dir / "twitch" / "oauth.json"
        tiktok.parent.mkdir(parents=True)
        twitch.parent.mkdir(parents=True)
        tiktok.write_text(json.dumps({
            "platform": "tiktok", "provider": "tiktok", "protocol": "oauth2", "enabled": True,
            "authorization_endpoint": self.base + "/authorize",
            "token_endpoint": self.base + "/token",
            "revoke_endpoint": self.base + "/revoke",
            "identity_endpoint": self.base + "/identity?platform=tiktok",
            "identity_fields": "open_id,display_name",
            "environments": {"sandbox": {
                "client_key_env": "STREAMIOV_TIKTOK_SANDBOX_CLIENT_KEY",
                "client_secret_env": "STREAMIOV_TIKTOK_SANDBOX_CLIENT_SECRET",
                "redirect_uri_env": "STREAMIOV_TIKTOK_SANDBOX_REDIRECT_URI",
                "allowed_scopes": ["user.info.basic"],
            }},
            "pkce_method": "S256", "pkce_challenge_encoding": "hex",
            "client_id_param": "client_key", "scope_separator": ",",
            "revoke_requires_secret": True, "token_storage": "server_only_encrypted",
        }), encoding="utf-8")
        twitch.write_text(json.dumps({
            "platform": "twitch", "provider": "twitch", "protocol": "oauth2", "enabled": True,
            "authorization_endpoint": self.base + "/authorize",
            "token_endpoint": self.base + "/token",
            "revoke_endpoint": self.base + "/revoke",
            "identity_endpoint": self.base + "/identity?platform=twitch",
            "required_scopes": ["channel:read:stream_key"],
            "client_id_env": "STREAMIOV_TWITCH_CLIENT_ID",
            "client_secret_env": "STREAMIOV_TWITCH_CLIENT_SECRET",
            "redirect_uri_env": "STREAMIOV_TWITCH_REDIRECT_URI",
            "client_id_param": "client_id", "scope_separator": " ",
            "rotate_refresh_token": True,
        }), encoding="utf-8")

    def _start_host(self):
        self.host = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler,
            Path(__file__).resolve().parents[1] / "dist" / "streamiov-homepage-worker" / "public",
            self.data_dir, registration_open=True,
        )
        self.host_url = f"http://127.0.0.1:{self.host.server_port}"
        for platform in ("tiktok", "twitch"):
            key = (f"STREAMIOV_TIKTOK_SANDBOX_REDIRECT_URI" if platform == "tiktok"
                   else "STREAMIOV_TWITCH_REDIRECT_URI")
            os.environ[key] = f"{self.host_url}/api/v1/platforms/{platform}/callback"
        self.host_thread = threading.Thread(target=self.host.serve_forever,
                                            kwargs={"poll_interval": 0.1}, daemon=True)
        self.host_thread.start()

    def _request(self, path: str, body: dict | None = None, *, opener=None,
                  redirect_uri_origin: str | None = None, method: str | None = None):
        headers = {}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Origin"] = redirect_uri_origin or self.host_url
            data = json.dumps(body).encode("utf-8")
        request = Request(self.host_url + path, data=data, headers=headers, method=method)
        client = opener or self.opener
        try:
            with client.open(request, timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def _json_request(self, path: str, body: dict | None = None, **kwargs):
        status, text = self._request(path, body, **kwargs)
        return status, json.loads(text)

    def _register(self, username: str) -> None:
        status, payload = self._json_request("/api/v1/auth/register", {
            "username": username, "password": "a-long-test-password-1234",
        })
        self.assertEqual(status, 201, payload)

    def _connect(self, platform: str) -> dict:
        status, payload = self._json_request(f"/api/v1/platforms/{platform}/connect", {})
        self.assertEqual(status, 200, payload)
        return payload

    def _callback(self, platform: str, state: str, code: str = "code-tiktok"):
        query = urlencode({"state": state, "code": code})
        return self._request(f"/api/v1/platforms/{platform}/callback?{query}")

    def test_tiktok_full_http_flow_with_pkce_encryption_refresh_and_restart(self):
        self._register("oauthuser")
        connect = self._connect("tiktok")
        query = parse_qs(urlsplit(connect["authorization_url"]).query)
        self.assertEqual(query["client_key"], ["tiktok-client"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["scope"], ["user.info.basic"])
        self.assertEqual(len(query["code_challenge"][0]), 64)
        self.assertEqual(query["redirect_uri"],
                         [f"{self.host_url}/api/v1/platforms/tiktok/callback"])

        stored = self.host.connection_store.find_pending_oauth_state("tiktok", connect["state"])
        expected = hashlib.sha256(stored["code_verifier"].encode("ascii")).hexdigest()
        self.assertEqual(query["code_challenge"], [expected])

        status, page = self._callback("tiktok", connect["state"])
        self.assertEqual(status, 200)
        self.assertIn("Verbindung eingerichtet", page)

        status, payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertEqual(status, 200)
        connection = payload["connection"]
        self.assertTrue(payload["config"]["configured"])
        self.assertTrue(connection["connected"])
        self.assertEqual(connection["account_id"], "creator-tiktok")
        self.assertEqual(connection["scopes"], ["user.info.basic"])
        for forbidden in ("access_token", "refresh_token", "access_token_encrypted"):
            self.assertNotIn(forbidden, connection)

        with closing(sqlite3.connect(self.host.connection_store.path)) as db:
            encrypted = db.execute(
                "SELECT access_token_encrypted, refresh_token_encrypted "
                "FROM platform_connections WHERE platform = 'tiktok'"
            ).fetchone()
        self.assertNotIn("access-tiktok", encrypted[0])
        self.assertNotIn("refresh-tiktok", encrypted[1])

        _, status_payload = self._json_request("/api/v1/status")
        self.assertTrue(status_payload["platform_integrations_ready"])
        self.assertTrue(status_payload["platform_configs"]["tiktok"]["ready"])

        status, refresh = self._json_request("/api/v1/platforms/tiktok/refresh", {})
        self.assertEqual(status, 200, refresh)
        self.assertNotEqual(refresh["status"]["token_expires_at"], connection["token_expires_at"])
        self.assertEqual(self.host.connection_store.get_refresh_token(self._user_id(), "tiktok"),
                         "refresh-rotated-1")

        self.host.shutdown()
        self.host.server_close()
        self.host_thread.join(timeout=3)
        self._start_host()
        status, payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["connection"]["connected"])

    def _user_id(self) -> str:
        status, payload = self._json_request("/api/v1/auth/me")
        self.assertEqual(status, 200, payload)
        return payload["user"]["id"]

    def test_twitch_flow_requires_granted_scope(self):
        self._register("twitchuser")
        connect = self._connect("twitch")
        query = parse_qs(urlsplit(connect["authorization_url"]).query)
        self.assertNotIn("code_challenge", query)
        self.assertEqual(query["scope"], ["channel:read:stream_key"])

        status, page = self._callback("twitch", connect["state"], code="code-twitch")
        self.assertEqual(status, 200)
        self.assertIn("Verbindung eingerichtet", page)
        status, payload = self._json_request("/api/v1/platforms/twitch")
        self.assertEqual(status, 200)
        self.assertTrue(payload["connection"]["connected"])
        self.assertEqual(payload["connection"]["account_name"], "creator_twitch")

    def test_provider_denial_state_replay_and_multi_user_isolation(self):
        self._register("aliceoauth")
        denied = self._connect("tiktok")
        status, page = self._request(
            f"/api/v1/platforms/tiktok/callback?{urlencode({'state': denied['state'], 'error': 'access_denied'})}"
        )
        self.assertEqual(status, 200)
        self.assertIn("authorization_denied", page)
        _, payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertFalse(payload["connection"]["authorization_pending"])
        self.assertEqual(payload["connection"]["last_error"], "authorization_denied")

        connect = self._connect("tiktok")
        status, page = self._callback("tiktok", connect["state"])
        self.assertEqual(status, 200)
        status, page = self._callback("tiktok", connect["state"])
        self.assertEqual(status, 200)
        self.assertIn("oauth_state_invalid_or_expired", page)

        self._register("boboauth")
        _, payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertIsNone(payload["connection"])

    def test_refresh_rejects_a_token_rotated_by_a_concurrent_request(self):
        self._register("staleuser")
        connect = self._connect("tiktok")
        self._callback("tiktok", connect["state"])
        store = self.host.connection_store
        original_update = store.update_tokens

        def rotate_then_retry_stale(*args, **kwargs):
            original_update(*args, **kwargs)
            stale = dict(kwargs)
            stale["expected_refresh_token"] = "refresh-tiktok"
            return original_update(*args, **stale)

        with patch.object(store, "update_tokens", side_effect=rotate_then_retry_stale):
            status, payload = self._json_request("/api/v1/platforms/tiktok/refresh", {})
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"], "refresh_token_rotated")
        self.assertEqual(store.get_refresh_token(self._user_id(), "tiktok"),
                         "refresh-rotated-1")

    def test_failed_refresh_marks_connection_for_reauthorization(self):
        self._register("refreshuser")
        connect = self._connect("tiktok")
        self._callback("tiktok", connect["state"], code="code-bad-refresh")
        status, payload = self._json_request("/api/v1/platforms/tiktok/refresh", {})
        self.assertEqual(status, 401, payload)
        self.assertEqual(payload["error"], "reauthorization_required")
        _, status_payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertTrue(status_payload["connection"]["needs_reauthorization"])
        self.assertFalse(status_payload["connection"]["connected"])
        self.assertIsNone(self.host.connection_store.get_refresh_token(self._user_id(), "tiktok"))

    def test_disconnect_revokes_provider_token_and_reports_revoke_failure(self):
        self._register("disconnectuser")
        connect = self._connect("tiktok")
        self._callback("tiktok", connect["state"], code="code-revoke-fail")
        status, payload = self._json_request("/api/v1/platforms/tiktok/disconnect", {})
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["revoked"])
        self.assertIn(payload["revoke_error"], {"oauth_provider_unavailable", "oauth_provider_rejected"})
        self.assertFalse(payload["status"]["connected"])

        connect = self._connect("tiktok")
        self._callback("tiktok", connect["state"])
        status, payload = self._json_request("/api/v1/platforms/tiktok/disconnect", {})
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["revoked"])
        self.assertFalse(payload["status"]["connected"])
        self.assertIn("access-revoke-fail", self.provider.revokes)

    def test_provider_errors_are_not_confused_with_successful_connections(self):
        self._register("erroruser")
        connect = self._connect("tiktok")
        status, page = self._callback("tiktok", connect["state"], code="unknown-code")
        self.assertEqual(status, 200)
        self.assertIn("invalid_grant", page)
        _, payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertFalse(payload["connection"]["connected"])
        self.assertEqual(payload["connection"]["last_error"], "invalid_grant")

    def test_non_post_methods_cannot_reach_oauth_write_routes(self):
        self._register("methoduser")
        for method in ("PUT", "PATCH", "DELETE"):
            status, payload = self._json_request("/api/v1/platforms/tiktok/connect", {}, method=method)
            self.assertEqual(status, 405, (method, payload))
            self.assertEqual(payload["error"], "method_not_allowed")
        status, payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertEqual(status, 200, payload)
        self.assertIsNone(payload["connection"])

    def test_callbacks_are_rate_limited_without_exhausting_connect_budget(self):
        callback = "/api/v1/platforms/tiktok/callback?state=unknown&code=unused"
        for attempt in range(12):
            status, page = self._request(callback)
            self.assertEqual(status, 200, (attempt, page))
            self.assertIn("oauth_state_invalid_or_expired", page)
        status, page = self._request(callback)
        self.assertEqual(status, 429, page)
        self.assertIn("too_many_attempts", page)
        self._register("callbacklimituser")
        connect = self._connect("tiktok")
        self.assertTrue(connect["ok"], connect)

    def test_callback_throttle_persists_across_host_restart(self):
        callback = "/api/v1/platforms/tiktok/callback?state=restart&code=unused"
        for attempt in range(12):
            status, page = self._request(callback)
            self.assertEqual(status, 200, (attempt, page))
        status, page = self._request(callback)
        self.assertEqual(status, 429, page)
        self.assertIn("too_many_attempts", page)

        self.host.shutdown()
        self.host.server_close()
        self.host_thread.join(timeout=3)
        self._start_host()

        status, page = self._request(callback)
        self.assertEqual(status, 429, page)
        self.assertIn("too_many_attempts", page)

    def test_oauth_endpoints_require_authentication_and_same_origin(self):
        self._register("originuser")
        anonymous = build_opener()
        status, payload = self._json_request("/api/v1/platforms", opener=anonymous)
        self.assertEqual(status, 401, payload)
        status, payload = self._json_request("/api/v1/platforms/tiktok/connect", {},
                                             redirect_uri_origin="https://evil.example")
        self.assertEqual(status, 403, payload)

    def test_chain_core_status_and_catalog_feed_the_studio_read_contract(self):
        self._register("chaincoreuser")
        status, payload = self._json_request("/api/v1/status")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["service"], "streamiov-host")
        self.assertEqual(payload["stage"], "local-account-api")
        self.assertTrue(payload["auth_ready"])
        self.assertTrue(payload["account_api_ready"])
        self.assertTrue(payload["catalog_ready"])
        self.assertTrue(payload["catalog_read_only"])
        self.assertTrue(payload["platform_connections_ready"])
        self.assertTrue(payload["platform_integrations_ready"])
        self.assertTrue(payload["platform_configs"]["tiktok"]["configured"])
        self.assertTrue(payload["platform_configs"]["twitch"]["configured"])

        status, catalog = self._json_request("/api/v1/catalog")
        self.assertEqual(status, 200, catalog)
        self.assertTrue(catalog["ok"])
        self.assertIn("counts", catalog)

    def test_chain_tiktok_oauth_callback_posts_a_token_free_success(self):
        self._register("chainoauthuser")
        connect = self._connect("tiktok")
        status, page = self._callback("tiktok", connect["state"])
        self.assertEqual(status, 200, page)
        self.assertIn("Verbindung eingerichtet", page)
        match = re.search(r"const payload=(\{.*?\});if\(window\.opener\)", page)
        self.assertIsNotNone(match, page)
        self.assertEqual(json.loads(match.group(1)), {
            "type": "streamiov-oauth-callback", "platform": "tiktok",
            "ok": True, "code": "connected",
        })

        status, payload = self._json_request("/api/v1/platforms/tiktok")
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["connection"]["connected"])
        self.assertEqual(payload["connection"]["account_id"], "creator-tiktok")
        for forbidden in ("access_token", "refresh_token", "access_token_encrypted"):
            self.assertNotIn(forbidden, payload["connection"])

    def test_chain_disconnect_revocation_failure_then_reconnect(self):
        self._register("chaindisconnectuser")
        connect = self._connect("tiktok")
        self._callback("tiktok", connect["state"], code="code-revoke-fail")
        status, payload = self._json_request("/api/v1/platforms/tiktok/disconnect", {})
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["revoked"])
        self.assertFalse(payload["status"]["connected"])
        self.assertIn("access-revoke-fail", self.provider.revokes)

        _, stored = self._json_request("/api/v1/platforms/tiktok")
        self.assertFalse(stored["connection"]["connected"])

        reconnect = self._connect("tiktok")
        self.assertNotEqual(reconnect["state"], connect["state"])
        status, page = self._callback("tiktok", reconnect["state"])
        self.assertEqual(status, 200, page)
        _, restored = self._json_request("/api/v1/platforms/tiktok")
        self.assertTrue(restored["connection"]["connected"])
        self.assertEqual(restored["connection"]["account_id"], "creator-tiktok")


class OAuthKeyGenerationTests(unittest.TestCase):
    def test_generate_oauth_key_creates_private_key_once(self):
        from host.server import main

        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "keys"
            self.assertEqual(main(["--generate-oauth-key", "--data-dir", str(data_dir)]), 0)
            key_path = data_dir / "oauth-token.key"
            self.assertTrue(key_path.is_file())
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            self.assertGreaterEqual(len(key_path.read_text(encoding="utf-8").strip()), 32)
            with self.assertRaises(SystemExit):
                main(["--generate-oauth-key", "--data-dir", str(data_dir)])
            crypto = TokenCrypto(data_dir)
            self.assertEqual(crypto.decrypt(crypto.encrypt("token")), "token")


if __name__ == "__main__":
    unittest.main()
