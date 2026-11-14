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

    def test_expired_lease_requeues_without_spending_the_retry_budget(self):
        self.queue.enqueue_plan([SpecialistTask("resume", "code", "resume from checkpoint")], max_attempts=1)
        first = self.queue.claim_next("worker-a")
        self.assertEqual(first.attempts, 1)
        with self.queue._connection() as connection:
            connection.execute("UPDATE specialist_tasks SET lease_until=0 WHERE task_id='resume'")
        resumed = self.queue.claim_next("worker-b")
        self.assertEqual(resumed.status, "running")
        self.assertEqual(resumed.attempts, 1)

    def test_worker_resumes_the_same_agent_checkpoint_after_an_interruption(self):
        from ai.core.agent import DevelopmentAgent
        from ai.runtime.task_queue import SpecialistWorker

        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        target = workspace / "ai" / "resumed.py"

        class Reply:
            def __init__(self, content):
                self.content = content

        class InterruptingProvider:
            def __init__(self):
                self.calls = 0
            def generate(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return Reply('{"tool":"write_file","arguments":{"path":"ai/resumed.py","content":"value = 9\\\\n"}}')
                raise RuntimeError("simulated process interruption")

        class FinishingProvider:
            def generate(self, **_kwargs):
                return Reply('{"final":"Resumed from the saved checkpoint."}')

        providers = [InterruptingProvider(), FinishingProvider()]
        def agent_factory(role):
            return DevelopmentAgent(
                provider=providers.pop(0),
                project_root=workspace,
                specialist=role,
                checkpoint_db=self.db,
            )

        self.queue.enqueue_plan(
            [SpecialistTask("resume-task", "code", "Create the resumable file")],
            max_attempts=2,
        )
        worker = SpecialistWorker(self.queue, "worker", agent_factory)
        first = worker.run_once()
        self.assertEqual(first.status, "queued")
        self.assertEqual(target.read_text(encoding="utf-8"), "value = 9\\n")

        second = worker.run_once()
        self.assertEqual(second.status, "succeeded")
        self.assertEqual(second.result, "Resumed from the saved checkpoint.")
        with self.queue._connection() as connection:
            checkpoint = connection.execute(
                "SELECT checkpoint_id FROM agent_checkpoints WHERE checkpoint_id='resume-task'"
            ).fetchone()
        self.assertIsNone(checkpoint)

    def test_worker_lease_loss_cancels_agent_and_releases_without_spending_attempt(self):
        import threading
        from ai.runtime.task_queue import SpecialistWorker

        self.queue.enqueue_plan([SpecialistTask("lease-loss", "testing", "wait for lease cancellation")])
        observed = {}

        def lose_lease(_task_id, _worker_id, **_kwargs):
            raise TaskQueueError("simulated lease loss")

        self.queue.heartbeat = lose_lease

        class WaitingAgent:
            def run(self, _prompt, *, checkpoint_id=None, cancel_event=None):
                observed["checkpoint_id"] = checkpoint_id
                observed["cancel_event"] = cancel_event
                if cancel_event is None or not cancel_event.wait(8):
                    raise AssertionError("worker did not cancel the active agent")
                raise RuntimeError("agent stopped after lease loss")

        worker = SpecialistWorker(self.queue, "worker", lambda _role: WaitingAgent(), lease_seconds=10)
        result = worker.run_once()
        queued = self.queue.get("lease-loss")
        self.assertEqual(result.status, "queued")
        self.assertEqual(queued.status, "queued")
        self.assertEqual(queued.attempts, 0)
        self.assertEqual(observed["checkpoint_id"], "lease-loss")
        self.assertTrue(observed["cancel_event"].is_set())

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
