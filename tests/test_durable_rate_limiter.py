import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path

from host.auth import DurableRateLimiter


class DurableRateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"

    def test_limit_survives_a_new_store_instance(self):
        first = DurableRateLimiter(self.data_dir, limit=2, window_seconds=60)
        now = 1_000_000.0
        self.assertTrue(first.allow("oauth_callback", "127.0.0.1", now=now))
        self.assertTrue(first.allow("oauth_callback", "127.0.0.1", now=now + 1))
        self.assertFalse(first.allow("oauth_callback", "127.0.0.1", now=now + 2))

        second = DurableRateLimiter(self.data_dir, limit=2, window_seconds=60)
        self.assertFalse(second.allow("oauth_callback", "127.0.0.1", now=now + 3))
        self.assertTrue(second.allow("oauth_callback", "127.0.0.2", now=now + 3))

    def test_attempts_expire_after_the_window(self):
        first = DurableRateLimiter(self.data_dir, limit=1, window_seconds=60)
        self.assertTrue(first.allow("oauth_callback", "192.0.2.8", now=500.0))
        self.assertFalse(first.allow("oauth_callback", "192.0.2.8", now=501.0))

        second = DurableRateLimiter(self.data_dir, limit=1, window_seconds=60)
        self.assertTrue(second.allow("oauth_callback", "192.0.2.8", now=561.0))

    def test_actions_and_addresses_have_separate_buckets(self):
        limiter = DurableRateLimiter(self.data_dir, limit=1, window_seconds=60)
        now = 900.0
        self.assertTrue(limiter.allow("oauth_callback", "198.51.100.1", now=now))
        self.assertFalse(limiter.allow("oauth_callback", "198.51.100.1", now=now))
        self.assertTrue(limiter.allow("oauth_connect", "198.51.100.1", now=now))
        self.assertTrue(limiter.allow("oauth_callback", "198.51.100.2", now=now))

    def test_maximum_distinct_buckets_is_enforced(self):
        limiter = DurableRateLimiter(self.data_dir, limit=2, max_keys=2, window_seconds=60)
        now = 700.0
        self.assertTrue(limiter.allow("oauth_callback", "203.0.113.1", now=now))
        self.assertTrue(limiter.allow("oauth_callback", "203.0.113.2", now=now))
        self.assertFalse(limiter.allow("oauth_callback", "203.0.113.3", now=now))
        self.assertTrue(limiter.allow("oauth_callback", "203.0.113.1", now=now))

    def test_client_address_is_not_written_to_disk(self):
        limiter = DurableRateLimiter(self.data_dir, limit=1, window_seconds=60)
        limiter.allow("oauth_callback", "203.0.113.7", now=800.0)
        for path in self.data_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"203.0.113.7", path.read_bytes())
        with closing(sqlite3.connect(limiter.database)) as db:
            buckets = [row[0] for row in db.execute(
                "SELECT bucket FROM oauth_rate_limit_attempts"
            )]
        self.assertEqual(len(buckets), 1)
        self.assertNotIn("203.0.113.7", buckets[0])

    def test_storage_failure_fails_closed(self):
        limiter = DurableRateLimiter(self.data_dir, limit=1, window_seconds=60)
        limiter.database = self.data_dir
        self.assertFalse(limiter.allow("oauth_callback", "127.0.0.1"))

    def test_missing_bucket_key_fails_closed(self):
        limiter = DurableRateLimiter(self.data_dir, limit=1, window_seconds=60)
        limiter._bucket_key = None
        self.assertFalse(limiter.allow("oauth_callback", "127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
