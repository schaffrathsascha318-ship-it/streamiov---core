import tempfile
import unittest
from pathlib import Path

from ai.core.orchestrator import SpecialistTask
from ai.runtime.task_queue import SpecialistTaskQueue, TaskQueueError


class PersistentTaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "state" / "tasks.sqlite3"
        self.queue = SpecialistTaskQueue(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_persists_and_claims_only_ready_tasks(self):
        self.queue.enqueue_plan([
            SpecialistTask("dependent", "studio", "integrate", ("foundation",)),
            SpecialistTask("foundation", "core", "define contract"),
            SpecialistTask("independent", "game", "build game"),
        ])
        first = self.queue.claim_next("worker-a")
        self.assertEqual(first.task_id, "foundation")
        self.assertEqual(first.status, "running")
        independent = self.queue.claim_next("worker-b")
        self.assertEqual(independent.task_id, "independent")
        self.queue.complete("independent", "worker-b", "game ready")
        self.queue.complete("foundation", "worker-a", "contract ready")
        next_task = self.queue.claim_next("worker-b")
        self.assertEqual(next_task.task_id, "dependent")
        reopened = SpecialistTaskQueue(self.db)
        self.assertEqual(reopened.get("foundation").status, "succeeded")

    def test_failed_prerequisite_skips_dependants_but_not_independent_tasks(self):
        self.queue.enqueue_plan([
            SpecialistTask("root", "core", "root task"),
            SpecialistTask("child", "studio", "child task", ("root",)),
            SpecialistTask("other", "game", "independent task"),
        ])
        claimed = self.queue.claim_next("worker")
        self.assertEqual(claimed.task_id, "root")
        self.queue.fail("root", "worker", "failed")
        self.assertEqual(self.queue.get("root").status, "failed")
        next_task = self.queue.claim_next("worker-2")
        self.assertEqual(next_task.task_id, "other")
        self.assertEqual(self.queue.get("child").status, "skipped")

    def test_failure_retries_only_within_configured_budget(self):
        self.queue.enqueue_plan([SpecialistTask("retry", "code", "retry me")], max_attempts=2)
        first = self.queue.claim_next("worker")
        self.assertEqual(self.queue.fail("retry", "worker", "transient"), "queued")
        second = self.queue.claim_next("worker")
        self.assertEqual(second.attempts, 2)
        self.assertEqual(self.queue.fail("retry", "worker", "again"), "failed")

    def test_worker_lease_must_match(self):
        self.queue.enqueue_plan([SpecialistTask("leased", "testing", "run checks")])
        self.queue.claim_next("worker-a")
        with self.assertRaises(TaskQueueError):
            self.queue.complete("leased", "worker-b", "not allowed")
        with self.assertRaises(TaskQueueError):
            self.queue.heartbeat("leased", "worker-b")

    def test_duplicate_ids_and_cycles_are_rejected_before_inserts(self):
        with self.assertRaises(TaskQueueError):
            self.queue.enqueue_plan([
                SpecialistTask("a", "core", "A"),
                SpecialistTask("a", "game", "duplicate"),
            ])
        with self.assertRaises(Exception):
            self.queue.enqueue_plan([
                SpecialistTask("a", "core", "A", ("b",)),
                SpecialistTask("b", "game", "B", ("a",)),
            ])
        self.assertEqual(self.queue.list_tasks(), [])

    def test_retry_count_is_bounded(self):
        with self.assertRaises(TaskQueueError):
            self.queue.enqueue_plan([SpecialistTask("bad", "core", "bad")], max_attempts=99)


    def test_worker_executes_a_task_with_the_assigned_specialist(self):
        from ai.runtime.task_queue import SpecialistWorker
        self.queue.enqueue_plan([SpecialistTask("work", "game", "make original game")])
        seen = []
        class Agent:
            def run(self, prompt, *, cancel_event=None):
                seen.append(prompt)
                return "game build prepared"
        worker = SpecialistWorker(self.queue, "worker", lambda role: Agent() if role == "game" else None)
        result = worker.run_once()
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(seen, ["make original game"])
        self.assertEqual(self.queue.get("work").result, "game build prepared")

    def test_worker_records_failure_and_uses_retry_budget(self):
        from ai.runtime.task_queue import SpecialistWorker
        self.queue.enqueue_plan([SpecialistTask("work", "testing", "run test")], max_attempts=2)
        class Agent:
            def run(self, _prompt, *, cancel_event=None):
                raise RuntimeError("test failed")
        worker = SpecialistWorker(self.queue, "worker", lambda _role: Agent())
        first = worker.run_once()
        self.assertEqual(first.status, "queued")
        self.assertEqual(self.queue.get("work").attempts, 1)
        second = worker.run_once()
        self.assertEqual(second.status, "failed")
        self.assertEqual(self.queue.get("work").attempts, 2)


    def test_expired_lease_cannot_be_renewed_completed_or_failed(self):
        self.queue.enqueue_plan([
            SpecialistTask("heartbeat", "testing", "heartbeat"),
            SpecialistTask("complete", "testing", "complete"),
            SpecialistTask("fail", "testing", "fail"),
        ])
        for task_id in ("heartbeat", "complete", "fail"):
            task = self.queue.claim_next("worker")
            self.assertEqual(task.task_id, task_id)
            with self.queue._connection() as connection:
                connection.execute("UPDATE specialist_tasks SET lease_until=0 WHERE task_id=?", (task_id,))
            if task_id == "heartbeat":
                with self.assertRaises(TaskQueueError):
                    self.queue.heartbeat(task_id, "worker")
            elif task_id == "complete":
                with self.assertRaises(TaskQueueError):
                    self.queue.complete(task_id, "worker", "late result")
            else:
                with self.assertRaises(TaskQueueError):
                    self.queue.fail(task_id, "worker", "late failure")

    def test_worker_cancels_agent_after_heartbeat_failure(self):
        import threading
        from ai.runtime.task_queue import SpecialistWorker

        self.queue.enqueue_plan([SpecialistTask("cancel", "testing", "cancel on lease loss")])
        heartbeat_failed = threading.Event()

        def failing_heartbeat(*args, **kwargs):
            heartbeat_failed.set()
            raise TaskQueueError("simulated lease loss")

        self.queue.heartbeat = failing_heartbeat

        class WaitingAgent:
            def run(self, _prompt, *, cancel_event=None):
                self.assert_event = cancel_event
                if cancel_event is None:
                    raise AssertionError("cancel_event was not provided")
                if not cancel_event.wait(6):
                    raise AssertionError("agent was not cancelled after heartbeat failure")
                return "cancelled"

        result = SpecialistWorker(
            self.queue, "worker", lambda _role: WaitingAgent(), lease_seconds=10
        ).run_once()

        self.assertTrue(heartbeat_failed.is_set())
        self.assertEqual(result.status, "failed")
        self.assertIn("lease lost", result.error.lower())
        self.assertEqual(self.queue.get("cancel").status, "running")

    def test_worker_renews_lease_during_a_long_running_agent_call(self):
        import time
        from ai.runtime.task_queue import SpecialistWorker
        self.queue.enqueue_plan([SpecialistTask("long", "testing", "long test")])
        calls = []
        original_heartbeat = self.queue.heartbeat
        def record_heartbeat(*args, **kwargs):
            calls.append(args[0])
            return original_heartbeat(*args, **kwargs)
        self.queue.heartbeat = record_heartbeat
        class SlowAgent:
            def run(self, _prompt, *, cancel_event=None):
                time.sleep(3.5)
                return "finished after lease renewal"
        result = SpecialistWorker(self.queue, "worker", lambda _role: SlowAgent(), lease_seconds=10).run_once()
        self.assertEqual(result.status, "succeeded")
        self.assertGreaterEqual(len(calls), 1)


    def test_worker_passes_multiple_prerequisite_results(self):
        from ai.runtime.task_queue import SpecialistWorker
        self.queue.enqueue_plan([
            SpecialistTask("final", "integration", "integrate everything", ("base-a", "base-b")),
            SpecialistTask("base-a", "core", "build base A"),
            SpecialistTask("base-b", "code", "build base B"),
        ])
        first = self.queue.claim_next("worker")
        self.queue.complete(first.task_id, "worker", "RESULT-A: interface ready")
        second = self.queue.claim_next("worker")
        self.queue.complete(second.task_id, "worker", "RESULT-B: implementation ready")
        seen = []
        class Agent:
            def run(self, prompt, *, cancel_event=None):
                seen.append(prompt)
                return "integration complete"
        result = SpecialistWorker(self.queue, "worker", lambda _role: Agent()).run_once()
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(seen), 1)
        self.assertIn("integrate everything", seen[0])
        self.assertIn("RESULT-A: interface ready", seen[0])
        self.assertIn("RESULT-B: implementation ready", seen[0])
        self.assertIn("UNTRUSTED REFERENCE DATA", seen[0])

    def test_worker_bounds_large_prerequisite_result(self):
        from ai.runtime.task_queue import SpecialistWorker
        self.queue.enqueue_plan([
            SpecialistTask("final", "integration", "integrate", ("base",)),
            SpecialistTask("base", "core", "prepare base"),
        ])
        base = self.queue.claim_next("worker")
        self.queue.complete(base.task_id, "worker", "X" * 12000)
        seen = []
        class Agent:
            def run(self, prompt, *, cancel_event=None):
                seen.append(prompt)
                return "done"
        result = SpecialistWorker(self.queue, "worker", lambda _role: Agent()).run_once()
        self.assertEqual(result.status, "succeeded")
        self.assertIn("[RESULT TRUNCATED]", seen[0])
        self.assertLess(len(seen[0]), 9000)

    def test_worker_does_not_run_when_prerequisite_result_is_missing(self):
        from ai.runtime.task_queue import SpecialistWorker
        self.queue.enqueue_plan([
            SpecialistTask("final", "integration", "integrate", ("base",)),
            SpecialistTask("base", "core", "prepare base"),
        ])
        base = self.queue.claim_next("worker")
        self.queue.complete(base.task_id, "worker", "base ready")
        original_get = self.queue.get
        self.queue.get = lambda task_id: None if task_id == "base" else original_get(task_id)
        called = []
        class Agent:
            def run(self, prompt, *, cancel_event=None):
                called.append(prompt)
                return "should not run"
        result = SpecialistWorker(self.queue, "worker", lambda _role: Agent()).run_once()
        self.assertEqual(result.status, "failed")
        self.assertEqual(called, [])

if __name__ == "__main__":
    unittest.main()
