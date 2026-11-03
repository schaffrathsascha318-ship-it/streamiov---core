import sqlite3
import tempfile
import unittest
from pathlib import Path

from host.auth import AuthError, AuthStore, PBKDF2_ITERATIONS, RequestRateLimiter


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = AuthStore(self.root / "state")

    def tearDown(self):
        self.temp.cleanup()

    def test_registration_hashes_password_and_session_token_and_roundtrips(self):
        password = "a-long-local-password-2026"
        user, token = self.store.register("Creator_01", password)
        self.assertEqual(user.username, "Creator_01")
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(self.store.user_for_token(token), user)
        db = sqlite3.connect(self.store.database)
        try:
            password_hash = db.execute("SELECT password_hash FROM users").fetchone()[0]
            token_hash = db.execute("SELECT token_hash FROM sessions").fetchone()[0]
        finally:
            db.close()
        self.assertTrue(password_hash.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"))
        self.assertNotIn(password, password_hash)
        self.assertNotIn(token.encode("ascii"), self.store.database.read_bytes())
        self.assertEqual(len(token_hash), 32)

    def test_login_is_case_insensitive_and_rejects_wrong_password_generically(self):
        user, _ = self.store.register("Local_User", "a-long-local-password")
        self.assertIsNone(self.store.login("local_user", "incorrect-password"))
        result = self.store.login("LOCAL_USER", "a-long-local-password")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], user)

    def test_logout_and_expiry_revoke_sessions(self):
        user, token = self.store.register("Session_User", "a-long-local-password")
        self.assertEqual(self.store.user_for_token(token).user_id, user.user_id)
        db = sqlite3.connect(self.store.database)
        try:
            db.execute("UPDATE sessions SET expires_at=1")
            db.commit()
        finally:
            db.close()
        self.assertIsNone(self.store.user_for_token(token, now=2))
        self.store.revoke(token)
        self.assertIsNone(self.store.user_for_token(token))

    def test_owner_password_reset_revokes_every_session(self):
        user, token = self.store.register("Reset_User", "a-long-local-password")
        self.assertTrue(self.store.reset_password(user.username, "a-new-local-password-2026"))
        self.assertIsNone(self.store.user_for_token(token))
        self.assertIsNone(self.store.login("Reset_User", "a-long-local-password"))
        self.assertIsNotNone(self.store.login("Reset_User", "a-new-local-password-2026"))
        self.assertFalse(self.store.reset_password("missing_user", "a-new-local-password-2026"))

    def test_registration_validates_username_and_password_length(self):
        for username, password in (("ab", "a-long-local-password"), ("Good_Name", "short"), ("has space", "a-long-local-password")):
            with self.subTest(username=username), self.assertRaises(AuthError):
                self.store.register(username, password)

    def test_rate_limit_expires_and_bounds_new_address_keys(self):
        limiter = RequestRateLimiter(limit=2, window_seconds=60, max_keys=1)
        self.assertTrue(limiter.allow("login", "127.0.0.1", now=1))
        self.assertTrue(limiter.allow("login", "127.0.0.1", now=2))
        self.assertFalse(limiter.allow("login", "127.0.0.1", now=3))
        self.assertFalse(limiter.allow("login", "192.0.2.1", now=4))
        self.assertTrue(limiter.allow("login", "127.0.0.1", now=62))


if __name__ == "__main__":
    unittest.main()
