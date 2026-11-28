"""Tests for the explicitly configured shared-file rate limiter."""
import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from host.server import DEFAULT_SITE_ROOT, Handler, StreamioVHTTPServer
from host.shared_rate_limiter import SharedRateLimiter, SharedRateLimiterError


ADDRESS = "203.0.113.7"


def _process_worker(database: str, results) -> None:
    limiter = SharedRateLimiter(database, namespace="process", limit=3, window_seconds=600)
    granted = sum(
        1 for _ in range(6)
        if limiter.allow("oauth_callback", ADDRESS, now=1000)
    )
    results.put(granted)


class SharedRateLimiterConfigTests(unittest.TestCase):
    def test_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "shared.sqlite3"
            invalid = (
                ({"database_path": ""}, SharedRateLimiterError),
                ({"database_path": database, "namespace": "bad\x00name"}, SharedRateLimiterError),
                ({"database_path": database, "limit": 0}, SharedRateLimiterError),
                ({"database_path": database, "window_seconds": 0}, SharedRateLimiterError),
                ({"database_path": database, "max_keys": 0}, SharedRateLimiterError),
            )
            for kwargs, expected in invalid:
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(expected):
                        SharedRateLimiter(**kwargs)
            database.write_text("not a sqlite database\n", encoding="utf-8")
            with self.assertRaises(SharedRateLimiterError):
                SharedRateLimiter(database)


class SharedRateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "shared" / "rate-limit.sqlite3"

    def test_budget_is_shared_between_instances_with_separate_data_dirs(self):
        first_dir = self.root / "host-a"
        second_dir = self.root / "host-b"
        first_dir.mkdir(mode=0o700)
        second_dir.mkdir(mode=0o700)
        first = SharedRateLimiter(self.database, namespace="auth", limit=2, window_seconds=600)
        second = SharedRateLimiter(self.database, namespace="auth", limit=2, window_seconds=600)
        self.assertTrue(first.allow("oauth_callback", ADDRESS, now=1000))
        self.assertTrue(first.allow("oauth_callback", ADDRESS, now=1001))
        self.assertFalse(second.allow("oauth_callback", ADDRESS, now=1002))
        self.assertEqual(first.status(now=1002)["active_attempts"], 2)
        self.assertEqual(first_dir.name, "host-a")
        self.assertEqual(second_dir.name, "host-b")
        connection = sqlite3.connect(self.database)
        try:
            values = connection.execute(
                "SELECT bucket FROM shared_rate_limit_attempts"
            ).fetchall()
            dump = "\n".join(str(row[0]) for row in values)
        finally:
            connection.close()
        self.assertNotIn(ADDRESS, dump)
        self.assertEqual(len(values), 2)

    def test_namespaces_and_windows_are_independent(self):
        auth = SharedRateLimiter(self.database, namespace="auth", limit=1, window_seconds=600)
        forum = SharedRateLimiter(self.database, namespace="forum", limit=1, window_seconds=600)
        self.assertTrue(auth.allow("report", ADDRESS, now=1000))
        self.assertFalse(auth.allow("report", ADDRESS, now=1000))
        self.assertTrue(forum.allow("report", ADDRESS, now=1000))
        short = SharedRateLimiter(self.database, namespace="short", limit=1, window_seconds=1)
        self.assertTrue(short.allow("report", ADDRESS, now=1000))
        self.assertTrue(short.allow("report", ADDRESS, now=1001.5))
        self.assertFalse(short.allow("report", ADDRESS, now=1001.6))

    def test_storage_failure_fails_closed(self):
        limiter = SharedRateLimiter(self.database, limit=1)
        self.assertTrue(limiter.allow("action", ADDRESS, now=1000))
        self.database.unlink()
        self.database.mkdir(mode=0o700)
        self.assertFalse(limiter.allow("action", ADDRESS, now=1001))
        self.assertFalse(limiter.status()["ok"])

    def test_shared_budget_is_enforced_between_processes(self):
        context = multiprocessing.get_context("fork")
        results = context.Queue()
        processes = [
            context.Process(target=_process_worker, args=(str(self.database), results))
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        granted = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(granted), 3)

    def test_host_wires_shared_limiters_from_explicit_path_and_env(self):
        limiter = SharedRateLimiter(self.database)
        self.assertTrue(limiter.status()["configured"])
        for key in ("auth_limiter", "forum_thread_limiter", "event_limiter", "wishbox_limiter"):
            with self.subTest(limiter=key):
                server = StreamioVHTTPServer(
                    ("127.0.0.1", 0), Handler, DEFAULT_SITE_ROOT, self.root / "data",
                    shared_rate_limit_db=self.database,
                )
                try:
                    self.assertIsInstance(getattr(server, key), SharedRateLimiter)
                    self.assertTrue(server.shared_rate_limit_status["ok"])
                finally:
                    server.server_close()
        with patch.dict(os.environ, {"STREAMIOV_SHARED_RATE_LIMIT_DB": str(self.database)}):
            server = StreamioVHTTPServer(("127.0.0.1", 0), Handler, DEFAULT_SITE_ROOT,
                                         self.root / "data")
            try:
                self.assertIsInstance(server.auth_limiter, SharedRateLimiter)
                self.assertIsInstance(server.wishbox_limiter, SharedRateLimiter)
                if server.connection_store is None:
                    self.assertNotIsInstance(server.oauth_limiter, SharedRateLimiter)
            finally:
                server.server_close()
        server = StreamioVHTTPServer(("127.0.0.1", 0), Handler, DEFAULT_SITE_ROOT,
                                     self.root / "data")
        try:
            self.assertNotIsInstance(server.auth_limiter, SharedRateLimiter)
            self.assertIsNone(server.shared_rate_limit_status)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
