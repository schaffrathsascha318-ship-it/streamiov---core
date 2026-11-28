"""Tests for OAuth provider configuration and fail-closed validation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from services.oauth.provider import (
    DEFAULT_CONFIG_DIR,
    OAuthProvider,
    OAuthProviderConfig,
    OAuthProviderError,
    platform_config_status,
)


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return self.payload


class _RedirectedResponse(_Response):
    def geturl(self) -> str:
        return "https://attacker.invalid/callback"


class OAuthProviderTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._directory.name) / "config"
        tiktok = self.config_dir / "tiktok"
        twitch = self.config_dir / "twitch"
        tiktok.mkdir(parents=True)
        twitch.mkdir(parents=True)
        (tiktok / "oauth.json").write_text(json.dumps({
            "platform": "tiktok", "enabled": True,
            "authorization_endpoint": "https://www.tiktok.com/v2/auth/authorize/",
            "token_endpoint": "https://open.tiktokapis.com/v2/oauth/token/",
            "revoke_endpoint": "https://open.tiktokapis.com/v2/oauth/revoke/",
            "environments": {
                "sandbox": {
                    "client_key_env": "TEST_TIKTOK_KEY",
                    "client_secret_env": "TEST_TIKTOK_SECRET",
                    "redirect_uri_env": "TEST_TIKTOK_REDIRECT",
                    "allowed_scopes": ["user.info.basic"],
                },
                "production": {
                    "client_key_env": "TEST_TIKTOK_KEY",
                    "client_secret_env": "TEST_TIKTOK_SECRET",
                    "redirect_uri_env": "TEST_TIKTOK_REDIRECT",
                    "allowed_scopes": ["user.info.basic"],
                },
            },
            "pkce_method": "S256", "pkce_challenge_encoding": "hex",
            "client_id_param": "client_key", "scope_separator": ",",
        }), encoding="utf-8")
        (twitch / "oauth.json").write_text(json.dumps({
            "platform": "twitch", "enabled": True,
            "authorization_endpoint": "https://id.twitch.tv/oauth2/authorize",
            "token_endpoint": "https://id.twitch.tv/oauth2/token",
            "revoke_endpoint": "https://id.twitch.tv/oauth2/revoke",
            "client_id_env": "TEST_TWITCH_ID",
            "client_secret_env": "TEST_TWITCH_SECRET",
            "redirect_uri_env": "TEST_TWITCH_REDIRECT",
            "required_scopes": ["channel:read:stream_key"],
            "client_id_param": "client_id", "scope_separator": " ",
            "rotate_refresh_token": True,
        }), encoding="utf-8")
        self.environment = patch.dict(os.environ, {
            "STREAMIOV_PLATFORM_CONFIG_DIR": str(self.config_dir),
            "STREAMIOV_PLATFORM_ENV": "sandbox",
            "TEST_TIKTOK_KEY": "client-key", "TEST_TIKTOK_SECRET": "client-secret",
            "TEST_TIKTOK_REDIRECT": "http://127.0.0.1:9999/callback",
            "TEST_TWITCH_ID": "twitch-id", "TEST_TWITCH_SECRET": "twitch-secret",
            "TEST_TWITCH_REDIRECT": "http://127.0.0.1:9999/callback",
        })
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self._directory.cleanup()

    def test_config_status_is_token_free_and_reports_missing_credentials(self):
        status = platform_config_status("tiktok")
        self.assertTrue(status["configured"])
        self.assertNotIn("client_secret", status)
        with patch.dict(os.environ, {"TEST_TIKTOK_SECRET": ""}):
            status = platform_config_status("tiktok")
        self.assertFalse(status["configured"])
        self.assertIn("client_secret", status["missing"])

    def test_tiktok_authorization_uses_hex_pkce_challenge(self):
        config = OAuthProviderConfig.from_environment("tiktok")
        authorization = OAuthProvider(config).create_authorization()
        query = parse_qs(urlsplit(authorization["url"]).query)
        expected = hashlib.sha256(authorization["code_verifier"].encode("ascii")).hexdigest()
        self.assertEqual(query["code_challenge"], [expected])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["scope"], ["user.info.basic"])

    def test_production_redirect_requires_https(self):
        with patch.dict(os.environ, {"STREAMIOV_PLATFORM_ENV": "production"}):
            with self.assertRaises(OAuthProviderError) as raised:
                OAuthProviderConfig.from_environment("tiktok")
        self.assertEqual(raised.exception.code, "production_redirect_requires_https")

    def test_twitch_refresh_requires_rotated_refresh_token(self):
        def opener(_request, **_kwargs):
            return _Response({
                "access_token": "new-access", "expires_in": 3600,
                "scope": ["channel:read:stream_key"],
            })

        config = OAuthProviderConfig.from_environment("twitch")
        with self.assertRaises(OAuthProviderError) as raised:
            OAuthProvider(config, opener=opener).refresh("old-refresh")
        self.assertEqual(raised.exception.code, "refresh_token_rotation_missing")

    def test_missing_required_scope_fails_closed(self):
        def opener(_request, **_kwargs):
            return _Response({
                "access_token": "access", "refresh_token": "refresh",
                "expires_in": 3600, "scope": [],
            })

        config = OAuthProviderConfig.from_environment("tiktok")
        with self.assertRaises(OAuthProviderError) as raised:
            OAuthProvider(config, opener=opener).refresh("refresh")
        self.assertEqual(raised.exception.code, "required_scope_not_granted")

    def test_authenticated_get_rejects_a_redirected_response(self):
        def opener(_request, **_kwargs):
            return _RedirectedResponse({"account_id": "victim"})

        config = replace(
            OAuthProviderConfig.from_environment("tiktok"),
            identity_endpoint="https://api.tiktok.test/user/",
        )
        with self.assertRaises(OAuthProviderError) as raised:
            OAuthProvider(config, opener=opener)._get(config.identity_endpoint, "bearer-secret")
        self.assertEqual(raised.exception.code, "oauth_provider_redirect_rejected")

    def test_default_config_dir_points_to_the_repository_config(self):
        self.assertEqual(DEFAULT_CONFIG_DIR.name, "platforms")
        self.assertEqual(DEFAULT_CONFIG_DIR.parent.name, "config")
        with patch.dict(os.environ, {}, clear=True):
            status = platform_config_status("tiktok")
        self.assertEqual(status["platform"], "tiktok")
        if status.get("error") == "oauth_config_unavailable":
            self.skipTest("OAuth config files are excluded from isolated task workspaces.")
        self.assertNotIn("error", status)


if __name__ == "__main__":
    unittest.main()
