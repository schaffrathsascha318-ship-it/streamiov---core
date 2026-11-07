"""Recovery and concurrent-claim regression tests for the durable task queue."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.core.orchestrator import SpecialistTask
from ai.runtime.task_queue import SpecialistTaskQueue, TaskQueueError


class TaskQueueRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "queue.sqlite3"
        self.queue = SpecialistTaskQueue(self.database)

    def test_expired_lease_is_requeued_when_retry_budget_remains(self):
        task = SpecialistTask("recover-me", "testing", "run recovery regression")
        with patch("ai.runtime.task_queue.time.time", return_value=1000.0):
            self.queue.enqueue_plan([task], max_attempts=2)
            first = self.queue.claim_next("worker-one", lease_seconds=10)
        self.assertEqual(first.status, "running")
        self.assertEqual(first.attempts, 1)

        with patch("ai.runtime.task_queue.time.time", return_value=1011.0):
            second = self.queue.claim_next("worker-two", lease_seconds=10)

        self.assertIsNotNone(second)
        self.assertEqual(second.task_id, "recover-me")
        self.assertEqual(second.status, "running")
        self.assertEqual(second.worker_id, "worker-two")
        self.assertEqual(second.attempts, 2)


    def test_abrupt_process_exit_recovers_persisted_lease_after_restart(self):
        task = SpecialistTask("process-restart", "testing", "recover after process restart")
        self.queue.enqueue_plan([task], max_attempts=2)
        script = """
import sys
from ai.runtime.task_queue import SpecialistTaskQueue
queue = SpecialistTaskQueue(sys.argv[1])
task = queue.claim_next("crashed-process", lease_seconds=10)
assert task is not None and task.status == "running"
print(task.task_id)
"""
        completed = subprocess.run(
            [sys.executable, "-c", script, str(self.database)],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(completed.stdout.strip(), "process-restart")
        # The child process has exited without completing or releasing its lease.
        with sqlite3.connect(self.database) as connection:
            lease_until = connection.execute(
                "SELECT lease_until FROM specialist_tasks WHERE task_id=?",
                ("process-restart",),
            ).fetchone()[0]
        restarted_queue = SpecialistTaskQueue(self.database)
        with patch("ai.runtime.task_queue.time.time", return_value=lease_until + 1):
            recovered = restarted_queue.claim_next("restarted-service", lease_seconds=30)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.task_id, "process-restart")
        self.assertEqual(recovered.status, "running")
        self.assertEqual(recovered.worker_id, "restarted-service")
        self.assertEqual(recovered.attempts, 2)
        events = restarted_queue.audit_log(limit=20)
        self.assertTrue(any(
            item["action"] == "task.lease_recovered"
            and item["task_id"] == "process-restart"
            and item["details"] == "new_status=queued"
            for item in events
        ))

    def test_expired_lease_exhausting_retry_budget_fails_closed(self):
        task = SpecialistTask("no-retry", "testing", "verify exhausted lease")
        with patch("ai.runtime.task_queue.time.time", return_value=2000.0):
            self.queue.enqueue_plan([task], max_attempts=1)
            self.queue.claim_next("worker-one", lease_seconds=10)

        with patch("ai.runtime.task_queue.time.time", return_value=2011.0):
            claimed = self.queue.claim_next("worker-two", lease_seconds=10)

        self.assertIsNone(claimed)
        stored = self.queue.get("no-retry")
        self.assertEqual(stored.status, "failed")
        self.assertEqual(stored.worker_id, "")
        self.assertIn("lease expired", stored.error.lower())

    def test_dependants_are_skipped_after_prerequisite_fails(self):
        plan = [
            SpecialistTask("prepare", "testing", "prepare"),
            SpecialistTask("dependent", "testing", "dependent", ("prepare",)),
        ]
        with patch("ai.runtime.task_queue.time.time", return_value=3000.0):
            self.queue.enqueue_plan(plan, max_attempts=1)
            claimed = self.queue.claim_next("worker-one", lease_seconds=30)
            self.queue.fail(claimed.task_id, "worker-one", "simulated failure")
            next_task = self.queue.claim_next("worker-two", lease_seconds=30)

        self.assertIsNone(next_task)
        self.assertEqual(self.queue.get("prepare").status, "failed")
        dependent = self.queue.get("dependent")
        self.assertEqual(dependent.status, "skipped")
        self.assertIn("prerequisite", dependent.error.lower())

    def test_concurrent_workers_cannot_claim_the_same_task(self):
        task = SpecialistTask("single-claim", "testing", "claim exactly once")
        self.queue.enqueue_plan([task])
        barrier = threading.Barrier(3)
        results = []
        failures = []

        def claim(worker_id):
            try:
                barrier.wait(timeout=5)
                results.append(self.queue.claim_next(worker_id, lease_seconds=30))
            except Exception as exc:
                failures.append(exc)

        threads = [
            threading.Thread(target=claim, args=("worker-one",)),
            threading.Thread(target=claim, args=("worker-two",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        claimed = [item for item in results if item is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].task_id, "single-claim")
        self.assertEqual(self.queue.get("single-claim").status, "running")

    def test_expired_worker_cannot_complete_task_after_recovery(self):
        task = SpecialistTask("stale-worker", "testing", "reject stale completion")
        with patch("ai.runtime.task_queue.time.time", return_value=4000.0):
            self.queue.enqueue_plan([task], max_attempts=2)
            self.queue.claim_next("worker-old", lease_seconds=10)

        with patch("ai.runtime.task_queue.time.time", return_value=4011.0):
            self.queue.claim_next("worker-new", lease_seconds=10)
            with self.assertRaisesRegex(TaskQueueError, "not running"):
                self.queue.complete("stale-worker", "worker-old", "stale result")

        current = self.queue.get("stale-worker")
        self.assertEqual(current.status, "running")
        self.assertEqual(current.worker_id, "worker-new")


    def test_heartbeat_rejects_boolean_and_non_integer_lease_values(self):
        task = SpecialistTask("heartbeat-validation", "testing", "validate lease input")
        self.queue.enqueue_plan([task])
        self.queue.claim_next("worker-one", lease_seconds=30)

        for invalid in (True, False, 10.5, "30"):
            with self.subTest(lease_seconds=invalid):
                with self.assertRaisesRegex(TaskQueueError, "lease_seconds"):
                    self.queue.heartbeat("heartbeat-validation", "worker-one", lease_seconds=invalid)

    def test_complete_uses_a_single_clock_read_for_lease_check_and_update(self):
        task = SpecialistTask("single-clock", "testing", "use one clock value")
        with patch("ai.runtime.task_queue.time.time", return_value=5000.0):
            self.queue.enqueue_plan([task])
            self.queue.claim_next("worker-one", lease_seconds=30)

        with patch("ai.runtime.task_queue.time.time", side_effect=[5001.0, AssertionError("clock read twice")]) as clock:
            self.queue.complete("single-clock", "worker-one", "done")

        self.assertEqual(clock.call_count, 1)
        stored = self.queue.get("single-clock")
        self.assertEqual(stored.status, "succeeded")
        self.assertEqual(stored.result, "done")


if __name__ == "__main__":
    unittest.main()
