import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ai.__main__ import main
from ai.runtime.task_queue import SpecialistTaskQueue


class QueueCliTests(unittest.TestCase):
    def test_enqueue_command_persists_without_starting_a_model_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "queue.sqlite3")
            output = StringIO()
            with patch("ai.__main__.provider_from_env", side_effect=AssertionError("enqueue must not start inference")), redirect_stdout(output):
                self.assertEqual(main(["--enqueue", "--queue-db", database, "--specialist", "game", "--task", "Build an original prototype"]), 0)
            record = json.loads(output.getvalue())
            self.assertEqual(record["specialist"], "game")
            self.assertEqual(record["status"], "queued")
            task = SpecialistTaskQueue(database).get(record["task_id"])
            self.assertEqual(task.prompt, "Build an original prototype")
            self.assertEqual(task.status, "queued")

    def test_worker_once_executes_and_persists_a_queued_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "queue.sqlite3")
            queue = SpecialistTaskQueue(database)
            from ai.core.orchestrator import SpecialistTask
            queue.enqueue_plan([SpecialistTask("task-1", "testing", "Run the checks")])

            class FakeProvider:
                def generate(self, *, system, messages):
                    class Reply:
                        content = '{"final":"All assigned checks completed."}'
                    return Reply()

            output = StringIO()
            with patch("ai.__main__.provider_from_env", return_value=FakeProvider()), redirect_stdout(output):
                self.assertEqual(main(["--worker-once", "--queue-db", database, "--worker-id", "test-worker"]), 0)
            response = json.loads(output.getvalue())
            self.assertEqual(response["task_id"], "task-1")
            self.assertEqual(response["status"], "succeeded")
            self.assertEqual(queue.get("task-1").result, "All assigned checks completed.")

    def test_idle_worker_exits_without_loading_a_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "queue.sqlite3")
            output = StringIO()
            with patch("ai.__main__.provider_from_env", side_effect=AssertionError("idle worker must not load model")), redirect_stdout(output):
                self.assertEqual(main(["--worker-once", "--queue-db", database]), 0)
            self.assertEqual(json.loads(output.getvalue()), {"status": "idle"})

    def test_queue_modes_require_database_and_enqueue_requires_task(self):
        with self.assertRaises(SystemExit):
            main(["--worker-once"])
        with self.assertRaises(SystemExit):
            main(["--enqueue", "--queue-db", "/tmp/unused-streamiov-queue.sqlite3"])


if __name__ == "__main__":
    unittest.main()
