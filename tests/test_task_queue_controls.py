"""Durable queue operator controls and audit-log regression tests."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai.core.orchestrator import SpecialistTask
from ai.runtime.task_queue import SpecialistTaskQueue, TaskQueueError


class TaskQueueControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "queue.sqlite3"
        self.queue = SpecialistTaskQueue(self.database)

    def test_pause_blocks_new_claims_and_resume_restores_them(self):
        self.queue.enqueue_plan([SpecialistTask("paused-task", "testing", "wait")])
        self.assertTrue(self.queue.pause(actor="operator"))
        self.assertTrue(self.queue.is_paused())
        self.assertIsNone(self.queue.claim_next("worker-one", lease_seconds=30))

        self.assertTrue(self.queue.resume(actor="operator"))
        self.assertFalse(self.queue.is_paused())
        claimed = self.queue.claim_next("worker-one", lease_seconds=30)
        self.assertEqual(claimed.task_id, "paused-task")
        self.assertEqual(claimed.status, "running")

    def test_repeated_pause_and_resume_are_idempotent(self):
        self.assertTrue(self.queue.pause(actor="operator"))
        self.assertFalse(self.queue.pause(actor="operator"))
        self.assertTrue(self.queue.resume(actor="operator"))
        self.assertFalse(self.queue.resume(actor="operator"))
        actions = [item["action"] for item in self.queue.audit_log()]
        self.assertEqual(actions, ["queue.resumed", "queue.paused"])

    def test_only_queued_tasks_can_be_cancelled(self):
        self.queue.enqueue_plan([
            SpecialistTask("first", "testing", "first"),
            SpecialistTask("second", "testing", "second"),
        ])
        running = self.queue.claim_next("worker-one", lease_seconds=30)
        with self.assertRaisesRegex(TaskQueueError, "Running tasks"):
            self.queue.cancel_task(running.task_id, actor="operator")

        cancelled = self.queue.cancel_task("second", actor="operator")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertIn("Cancelled", cancelled.error)
        self.assertEqual(self.queue.get("first").status, "running")

    def test_cancelled_prerequisite_skips_dependants(self):
        self.queue.enqueue_plan([
            SpecialistTask("prerequisite", "testing", "prepare"),
            SpecialistTask("dependent", "testing", "follow up", ("prerequisite",)),
        ])
        self.queue.cancel_task("prerequisite", actor="operator")
        self.assertIsNone(self.queue.claim_next("worker-one", lease_seconds=30))
        self.assertEqual(self.queue.get("dependent").status, "skipped")

    def test_audit_log_records_actor_and_rejects_mutation(self):
        self.queue.pause(actor="release-manager")
        self.queue.resume(actor="release-manager")
        events = self.queue.audit_log(limit=10)
        self.assertEqual([event["actor"] for event in events], ["release-manager", "release-manager"])
        self.assertEqual([event["action"] for event in events], ["queue.resumed", "queue.paused"])

        with sqlite3.connect(self.database) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM queue_audit WHERE audit_id=1")

    def test_existing_queue_database_migrates_without_losing_tasks(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """
                CREATE TABLE specialist_tasks (
                    task_id TEXT PRIMARY KEY,
                    queue_order INTEGER NOT NULL DEFAULT 0,
                    specialist TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','skipped')),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 5),
                    result TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    worker_id TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO specialist_tasks(task_id, specialist, prompt, depends_on, status, max_attempts, created_at, updated_at) VALUES ('legacy-task', 'testing', 'keep me', '[]', 'queued', 1, 1, 1)"
            )

        migrated = SpecialistTaskQueue(self.database)
        self.assertEqual(migrated.get("legacy-task").status, "queued")
        cancelled = migrated.cancel_task("legacy-task", actor="migration-test")
        self.assertEqual(cancelled.status, "cancelled")

    def test_invalid_actors_and_audit_limits_are_rejected(self):
        with self.assertRaises(TaskQueueError):
            self.queue.pause(actor=" ")
        for limit in (True, 0, 1001, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(TaskQueueError):
                    self.queue.audit_log(limit=limit)


if __name__ == "__main__":
    unittest.main()
