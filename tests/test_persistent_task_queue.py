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
            def run(self, prompt):
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
            def run(self, _prompt):
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
            def run(self, _prompt):
                time.sleep(3.5)
                return "finished after lease renewal"
        result = SpecialistWorker(self.queue, "worker", lambda _role: SlowAgent(), lease_seconds=10).run_once()
        self.assertEqual(result.status, "succeeded")
        self.assertGreaterEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
