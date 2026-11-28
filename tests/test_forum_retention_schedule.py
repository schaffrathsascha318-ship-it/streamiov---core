"""Tests for the opt-in local forum retention schedule."""
import contextlib
import io
import json
import sqlite3
import stat
import tempfile
import time
import unittest
from pathlib import Path

from host.auth import User
from host.forum import ForumStore
from host.retention import (DEFAULT_POLICY_PATH, ForumRetentionScheduler,
                            load_retention_policy)
from host.server import main


ENABLED_POLICY = {
    "enabled": True,
    "interval_seconds": 3600,
    "state_root": "retention-state",
    "error": None,
}


def _user(name="Forum_User", user_id="a" * 32):
    return User(user_id=user_id, username=name, created_at=1)


class FakeStore:
    def __init__(self, data_dir, *, fail=False):
        self.data_dir = data_dir
        self.fail = fail
        self.calls = []

    def apply_retention(self, *, now=None):
        self.calls.append(now)
        if self.fail:
            raise OSError("simulated retention failure")
        return {"ok": True, "deleted": {"deleted_threads": 2}}


class ForumRetentionPolicyTests(unittest.TestCase):
    def test_checked_in_policy_is_disabled_and_requires_owner_review(self):
        policy = load_retention_policy()
        self.assertTrue(DEFAULT_POLICY_PATH.is_file())
        self.assertFalse(policy["enabled"])
        self.assertIsNone(policy["error"])
        scheduler = ForumRetentionScheduler(Path(tempfile.mkdtemp()), policy=policy)
        status = scheduler.status()
        self.assertTrue(status["ok"])
        self.assertFalse(status["policy"]["enabled"])
        self.assertIn("REVIEW_REQUIRED", status["legal_status"])
        self.assertEqual(status["production_status"], "NOT_VERIFIED")

    def test_invalid_policies_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {
                "wrong-type": "[]",
                "no-schedule": "{}",
                "bad-flag": '{"schedule": {"enabled": "yes"}}',
                "tiny-interval": '{"schedule": {"enabled": true, "interval_minutes": 1}}',
                "huge-interval": '{"schedule": {"enabled": true, "interval_minutes": 10081}}',
                "escaping-root": '{"schedule": {"enabled": true, "state_root": "../outside"}}',
                "broken-json": "{",
            }
            for name, content in cases.items():
                with self.subTest(case=name):
                    path = root / (name + ".json")
                    path.write_text(content, encoding="utf-8")
                    policy = load_retention_policy(path)
                    self.assertIsNotNone(policy["error"], name)
                    self.assertFalse(policy["enabled"], name)
            missing = load_retention_policy(root / "absent.json")
            self.assertIsNotNone(missing["error"])


class ForumRetentionSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir(mode=0o700)

    def test_disabled_schedule_does_not_run_or_write_state(self):
        store = FakeStore(self.data)
        scheduler = ForumRetentionScheduler(self.data, policy=dict(ENABLED_POLICY, enabled=False),
                                            store_factory=lambda data: store)
        report = scheduler.run_once(at=1000)
        self.assertFalse(report["ran"])
        self.assertEqual(report["reason"], "disabled")
        self.assertFalse(store.calls)
        self.assertFalse(scheduler.start())
        self.assertFalse(scheduler.state_path.exists())

    def test_scheduler_tracks_due_state_and_is_idempotent(self):
        store = FakeStore(self.data)
        scheduler = ForumRetentionScheduler(self.data, policy=ENABLED_POLICY,
                                            store_factory=lambda data: store, now=lambda: 1001)
        first = scheduler.run_once(force=True, at=1000)
        self.assertTrue(first["ok"])
        self.assertEqual(first["deleted"], {"deleted_threads": 2})
        self.assertEqual(store.calls, [1000])
        not_due = scheduler.run_once(at=1001)
        self.assertFalse(not_due["ran"])
        self.assertEqual(not_due["reason"], "not_due")
        self.assertFalse(scheduler.status()["due_now"])
        second = scheduler.run_once(force=True, at=3700)
        self.assertTrue(second["ok"])
        self.assertEqual(len(store.calls), 2)
        status = scheduler.status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["state"]["run_count"], 2)
        self.assertEqual(status["state"]["failure_count"], 0)
        self.assertEqual(status["state"]["last_result"]["deleted"], "2")
        self.assertFalse(status["due_now"])
        self.assertEqual(status["state"]["next_run_at"], "1970-01-01T02:01:40+00:00")
        self.assertEqual(stat.S_IMODE(scheduler.state_path.stat().st_mode), 0o600)

    def test_failed_cycle_is_recorded_without_success(self):
        store = FakeStore(self.data, fail=True)
        scheduler = ForumRetentionScheduler(self.data, policy=ENABLED_POLICY,
                                            store_factory=lambda data: store)
        report = scheduler.run_once(force=True, at=1000)
        self.assertFalse(report["ok"])
        self.assertIn("simulated retention failure", report["error"])
        status = scheduler.status()
        self.assertEqual(status["state"]["failure_count"], 1)
        self.assertIsNone(status["state"]["last_success_at"])
        self.assertEqual(status["state"]["last_result"],
                         {"ok": "False", "error": "simulated retention failure"})

    def test_tampered_state_blocks_automatic_deletion(self):
        store = FakeStore(self.data)
        scheduler = ForumRetentionScheduler(self.data, policy=ENABLED_POLICY,
                                            store_factory=lambda data: store)
        scheduler.root.mkdir(mode=0o700)
        scheduler.state_path.write_text('{"schema_version": 99}\n', encoding="utf-8")
        report = scheduler.run_once(at=1000)
        self.assertFalse(report["ok"])
        self.assertFalse(store.calls)
        self.assertIsNotNone(scheduler.status()["state"]["state_error"])

    def test_real_soft_deleted_thread_expires_through_scheduler(self):
        store = ForumStore(self.data)
        thread = store.create_thread(_user(), "Altes Thema", "Ein alter Beitrag")
        visible = store.create_thread(_user(), "Sichtbares Thema", "Ein neuer Beitrag")
        self.assertTrue(store.delete_thread(thread["id"]))
        cutoff = int(time.time()) - 200 * 86_400
        connection = sqlite3.connect(store.database)
        try:
            connection.execute("UPDATE threads SET deleted_at = ? WHERE thread_id = ?",
                               (cutoff, thread["id"]))
            connection.commit()
        finally:
            connection.close()
        scheduler = ForumRetentionScheduler(self.data, policy=ENABLED_POLICY)
        report = scheduler.run_once(force=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["deleted"]["deleted_threads"], 1)
        snapshot = {item["id"] for item in store.moderation_snapshot()
                    if item.get("kind") == "thread"}
        self.assertNotIn(thread["id"], snapshot)
        self.assertIn(visible["id"], snapshot)

    def test_host_cli_reports_and_runs_the_schedule(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data),
                                   "--forum-retention-schedule-status"]), 0)
        status = json.loads(output.getvalue())
        self.assertTrue(status["ok"])
        self.assertFalse(status["policy"]["enabled"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data),
                                   "--forum-retention-schedule-run"]), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report["ok"])
        self.assertTrue(report["ran"])
        self.assertTrue((self.data / "forum-retention" / "forum-retention-schedule.json").is_file())

    def test_host_cli_accepts_explicit_enabled_policy(self):
        policy_path = Path(self.temp.name) / "enabled.json"
        policy_path.write_text(json.dumps({
            "schedule": {"enabled": True, "interval_minutes": 60, "state_root": "opt-in-state"}
        }), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data),
                                   "--forum-retention-policy", str(policy_path),
                                   "--forum-retention-schedule-status"]), 0)
        status = json.loads(output.getvalue())
        self.assertTrue(status["ok"])
        self.assertTrue(status["policy"]["enabled"])
        self.assertTrue(status["due_now"])
        self.assertEqual(status["policy"]["state_root"], "opt-in-state")


if __name__ == "__main__":
    unittest.main()
