"""Tests for local encrypted OAuth connection persistence."""

from __future__ import annotations

from contextlib import closing
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.oauth.connection_service import (
    PLATFORMS,
    ConnectionError,
    ConnectionStore,
)
from services.oauth.token_crypto import TokenCrypto, TokenCryptoError


class TokenCryptoTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.secret = "unit-test-token-secret-0123456789"

    def tearDown(self):
        self._directory.cleanup()

    def test_encrypt_decrypt_round_trip(self):
        crypto = TokenCrypto(self._directory.name, secret=self.secret)
        envelope = crypto.encrypt("plain-access-token")
        self.assertNotIn("plain-access-token", envelope)
        self.assertEqual(crypto.decrypt(envelope), "plain-access-token")
        self.assertNotEqual(crypto.encrypt("plain-access-token"), envelope)

    def test_tampered_envelope_is_rejected(self):
        crypto = TokenCrypto(self._directory.name, secret=self.secret)
        envelope = crypto.encrypt("plain-access-token")
        payload = json.loads(envelope)
        payload["ciphertext"] = "AAAA"
        with self.assertRaises(TokenCryptoError):
            crypto.decrypt(json.dumps(payload))

    def test_missing_key_fails_closed(self):
        with patch.dict(os.environ, {"STREAMIOV_TOKEN_KEY": ""}):
            with self.assertRaises(TokenCryptoError):
                TokenCrypto(self._directory.name)

    def test_key_file_is_supported(self):
        key_file = Path(self._directory.name) / "oauth-token.key"
        key_file.write_text(self.secret, encoding="utf-8")
        with patch.dict(os.environ, {"STREAMIOV_TOKEN_KEY": ""}):
            crypto = TokenCrypto(self._directory.name)
        self.assertEqual(crypto.decrypt(crypto.encrypt("token")), "token")


class ConnectionStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.crypto = TokenCrypto(self._directory.name, secret="unit-test-token-secret")
        self.store = ConnectionStore(self._directory.name, crypto=self.crypto)

    def tearDown(self):
        self._directory.cleanup()

    def _save(self, state="state", account_id="creator-1", expires_in=3600):
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
        self.store.save_verified_connection(
            user_id=1,
            platform="twitch",
            state=state,
            account_id=account_id,
            account_name="Creator",
            access_token="access-plain",
            refresh_token="refresh-plain",
            expires_at=expires_at,
            scopes=["channel:read"],
            metadata={"source": "unit-test"},
        )

    def test_state_is_hashed_and_single_use(self):
        state = self.store.create_oauth_state(1, "twitch")
        self.assertTrue(self.store.verify_oauth_state(1, "twitch", state))
        self.assertFalse(self.store.verify_oauth_state(1, "twitch", state + "x"))
        self.assertFalse(self.store.verify_oauth_state(2, "twitch", state))
        with closing(sqlite3.connect(self.store.path)) as db:
            stored = db.execute(
                "SELECT oauth_state_hash FROM platform_connections"
            ).fetchone()[0]
        self.assertNotEqual(stored, state)
        self.store.clear_oauth_state(1, "twitch")
        self.assertFalse(self.store.verify_oauth_state(1, "twitch", state))

    def test_expired_state_cannot_save_connection(self):
        state = self.store.create_oauth_state(1, "twitch")
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute(
                "UPDATE platform_connections SET oauth_state_expires_at = ?", (past,)
            )
            db.commit()
        with self.assertRaises(ConnectionError):
            self._save(state)

    def test_save_requires_matching_verified_state(self):
        self.store.create_oauth_state(1, "twitch")
        with self.assertRaises(ConnectionError):
            self._save("wrong-state")

    def test_connection_is_encrypted_and_status_never_exposes_tokens(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state)
        status = self.store.get_connection_status(1, "twitch")
        self.assertTrue(status["connected"])
        self.assertEqual(status["account_id"], "creator-1")
        self.assertEqual(status["scopes"], ["channel:read"])
        for forbidden in (
            "access_token", "refresh_token",
            "access_token_encrypted", "refresh_token_encrypted",
        ):
            self.assertNotIn(forbidden, status)
        with closing(sqlite3.connect(self.store.path)) as db:
            stored = db.execute(
                """
                SELECT access_token_encrypted, refresh_token_encrypted
                FROM platform_connections
                """
            ).fetchone()
        self.assertNotIn("access-plain", stored[0])
        self.assertNotIn("refresh-plain", stored[1])
        self.assertEqual(self.store.get_tokens(1, "twitch"), ("access-plain", "refresh-plain"))

    def test_expired_connection_is_not_reported_connected(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state, expires_in=-1)
        status = self.store.get_connection_status(1, "twitch")
        self.assertFalse(status["connected"])
        self.assertTrue(status["token_expired"])
        self.assertEqual(status["connection_status"], "expired")
        self.assertIsNone(self.store.get_tokens(1, "twitch"))

    def test_disconnect_clears_tokens_and_authorization(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state)
        self.store.disconnect_platform(1, "twitch")
        status = self.store.get_connection_status(1, "twitch")
        self.assertFalse(status["connected"])
        self.assertEqual(status["status"], "disconnected")
        self.assertEqual(status["authorization_state"], "not_authorized")
        self.assertIsNone(status["account_id"])
        self.assertIsNone(self.store.get_tokens(1, "twitch"))

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(ConnectionError):
            self.store.create_oauth_state(1, "unknown")
        self.assertEqual(PLATFORMS, frozenset({"twitch", "tiktok"}))

    def test_host_style_user_ids_are_scoped(self):
        state = self.store.create_oauth_state("user-a-0123456789abcdef", "twitch")
        self._save_with_user("user-a-0123456789abcdef", state)
        status = self.store.get_connection_status("user-a-0123456789abcdef", "twitch")
        self.assertTrue(status["connected"])
        self.assertIsNone(self.store.get_connection_status("user-b-0123456789abcdef", "twitch"))
        self.assertIsNone(self.store.get_tokens("user-b-0123456789abcdef", "twitch"))

    def _save_with_user(self, user_id, state, expires_in=3600):
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
        self.store.save_verified_connection(
            user_id=user_id, platform="twitch", state=state, account_id="creator-1",
            account_name="Creator", access_token="access-plain",
            refresh_token="refresh-plain", expires_at=expires_at,
            scopes=["channel:read"], metadata={"source": "unit-test"},
        )

    def test_pending_state_is_lookupable_without_user_session(self):
        state = self.store.create_oauth_state(
            1, "tiktok", state="pending-state", code_verifier="verifier-1234567890",
            redirect_uri="http://127.0.0.1:9999/api/v1/platforms/tiktok/callback",
            scopes=["user.info.basic"],
        )
        pending = self.store.find_pending_oauth_state("tiktok", state)
        self.assertEqual(pending["user_id"], "1")
        self.assertEqual(pending["code_verifier"], "verifier-1234567890")
        self.assertEqual(pending["redirect_uri"],
                         "http://127.0.0.1:9999/api/v1/platforms/tiktok/callback")
        self.assertEqual(pending["scopes"], ["user.info.basic"])
        self.assertIsNone(self.store.find_pending_oauth_state("twitch", state))
        self.assertIsNone(self.store.find_pending_oauth_state("tiktok", "wrong"))

    def test_expired_access_still_allows_refresh_token_retrieval(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state, expires_in=-1)
        self.assertIsNone(self.store.get_tokens(1, "twitch"))
        self.assertEqual(self.store.get_refresh_token(1, "twitch"), "refresh-plain")

    def test_update_tokens_rotates_tokens_and_scopes(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.store.update_tokens(1, "twitch", "access-rotated", refresh_token="refresh-rotated",
                                 expires_at=expires_at, scopes=["channel:read:stream_key"])
        self.assertEqual(self.store.get_tokens(1, "twitch"),
                         ("access-rotated", "refresh-rotated"))
        status = self.store.get_connection_status(1, "twitch")
        self.assertEqual(status["scopes"], ["channel:read:stream_key"])
        self.assertEqual(status["token_expires_at"], expires_at)
        self.assertTrue(status["connected"])

    def test_update_tokens_rejects_a_refresh_token_that_was_already_rotated(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.store.update_tokens(
            1, "twitch", "access-rotated", refresh_token="refresh-rotated",
            expires_at=expires_at, expected_refresh_token="refresh-plain",
        )
        with self.assertRaises(ConnectionError) as raised:
            self.store.update_tokens(
                1, "twitch", "access-stale", refresh_token="refresh-stale",
                expires_at=expires_at, expected_refresh_token="refresh-plain",
            )
        self.assertIn("already rotated", str(raised.exception))
        self.assertEqual(self.store.get_tokens(1, "twitch"),
                         ("access-rotated", "refresh-rotated"))

    def test_failed_provider_error_preserves_a_valid_connection(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state)
        self.store.record_oauth_error(1, "twitch", "provider_unavailable")
        status = self.store.get_connection_status(1, "twitch")
        self.assertTrue(status["connected"])
        self.assertEqual(status["last_error"], "provider_unavailable")

    def test_reauthorization_required_clears_all_tokens(self):
        state = self.store.create_oauth_state(1, "twitch")
        self._save(state)
        self.store.mark_reauthorization_required(1, "twitch", "invalid_grant")
        status = self.store.get_connection_status(1, "twitch")
        self.assertFalse(status["connected"])
        self.assertTrue(status["needs_reauthorization"])
        self.assertIsNone(status["account_id"])
        self.assertIsNone(self.store.get_refresh_token(1, "twitch"))

    def test_fail_oauth_state_records_error_without_a_session(self):
        state = self.store.create_oauth_state(1, "twitch")
        user_id = self.store.fail_oauth_state("twitch", state, "access_denied")
        self.assertEqual(user_id, "1")
        status = self.store.get_connection_status(1, "twitch")
        self.assertEqual(status["last_error"], "access_denied")
        self.assertFalse(status["authorization_pending"])
        self.assertIsNone(self.store.find_pending_oauth_state("twitch", state))


class TokenRotationTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._directory.cleanup()

    def test_previous_key_decrypts_envelopes_from_before_rotation(self):
        old = TokenCrypto(self._directory.name, secret="old-token-key-0123456789")
        envelope = old.encrypt("secret-token")
        new = TokenCrypto(self._directory.name, secret="new-token-key-0123456789",
                          previous_secret="old-token-key-0123456789")
        self.assertEqual(new.decrypt(envelope), "secret-token")
        rotated = new.encrypt("secret-token")
        self.assertEqual(new.decrypt(rotated), "secret-token")
        self.assertNotEqual(json.loads(envelope)["kid"], json.loads(rotated)["kid"])
        with self.assertRaises(TokenCryptoError):
            old.decrypt(rotated)

    def test_key_file_permissions_are_tightened(self):
        key_file = Path(self._directory.name) / "oauth-token.key"
        key_file.write_text("private-token-key-0123456789", encoding="utf-8")
        os.chmod(key_file, 0o644)
        with patch.dict(os.environ, {"STREAMIOV_TOKEN_KEY": ""}):
            crypto = TokenCrypto(self._directory.name)
        self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(crypto.decrypt(crypto.encrypt("token")), "token")


if __name__ == "__main__":
    unittest.main()
