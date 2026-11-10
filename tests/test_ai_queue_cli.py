import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ai.__main__ import main
from ai.runtime.task_queue import SpecialistTaskQueue


class QueueCliTests(unittest.TestCase):
    def test_enqueue_accepts_one_and_8000_character_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index, task_text in enumerate(("x", "x" * 8000)):
                database = str(Path(tmp) / f"queue-{index}.sqlite3")
                output = StringIO()
                with patch("ai.__main__.provider_from_env", side_effect=AssertionError("enqueue must not start inference")), redirect_stdout(output):
                    self.assertEqual(main(["--enqueue", "--queue-db", database, "--task", task_text]), 0)
                task_id = json.loads(output.getvalue())["task_id"]
                self.assertEqual(SpecialistTaskQueue(database).get(task_id).prompt, task_text)

    def test_invalid_task_rejected_before_provider_or_queue_access(self):
        cases = [
            (["--task", ""], "direct"),
            (["--task", " \t\n"], "direct"),
            (["--enqueue", "--queue-db", "unused.sqlite3", "--task", "x" * 8001], "enqueue"),
            (["--plan-and-enqueue", "--queue-db", "unused.sqlite3", "--task", "x" * 8001], "plan"),
            (["--enqueue", "--queue-db", "unused.sqlite3", "--task", " \t"], "enqueue"),
            (["--plan-and-enqueue", "--queue-db", "unused.sqlite3", "--task", " \t"], "plan"),
        ]
        for argv, _mode in cases:
            with self.subTest(argv=argv[:2]):
                with patch("ai.__main__.provider_from_env", side_effect=AssertionError("provider must not be called")), \
                        patch("ai.__main__.SpecialistTaskQueue", side_effect=AssertionError("queue must not be opened")), \
                        redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_plan_and_enqueue_accepts_8000_character_task_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "queue.sqlite3")
            class Planner:
                def plan(self, task):
                    assert len(task) == 8000
                    return []
            with patch("ai.__main__.provider_from_env", return_value=object()), \
                    patch("ai.__main__.SpecialistPlanner", return_value=Planner()), \
                    patch("ai.__main__.SpecialistTaskQueue") as queue, redirect_stdout(StringIO()):
                self.assertEqual(main(["--plan-and-enqueue", "--queue-db", database, "--task", "x" * 8000]), 0)
            queue.return_value.enqueue_plan.assert_called_once_with([])

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


    def test_worker_loop_cli_accepts_supervised_mode(self):
        from ai.__main__ import build_parser
        args = build_parser().parse_args([
            "--worker-loop", "--queue-db", "/tmp/streamiov-queue.sqlite3",
            "--worker-id", "service-worker", "--poll-seconds", "3", "--max-tasks", "4",
        ])
        self.assertTrue(args.worker_loop)
        self.assertEqual(args.poll_seconds, 3)
        self.assertEqual(args.max_tasks, 4)


    def test_core_planner_splits_goal_and_enqueues_specialist_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "queue.sqlite3")
            class PlannerProvider:
                def generate(self, *, system, messages):
                    class Reply:
                        content = '{"tasks":[{"id":"core","specialist":"core","prompt":"Define contract","depends_on":[]},{"id":"game","specialist":"game","prompt":"Build original game","depends_on":[]}]}'
                    return Reply()
            output = StringIO()
            with patch("ai.__main__.provider_from_env", return_value=PlannerProvider()), redirect_stdout(output):
                self.assertEqual(main(["--plan-and-enqueue", "--queue-db", database, "--task", "Build a new STREAMIOV feature"]), 0)
            response = json.loads(output.getvalue())
            self.assertEqual(response["status"], "queued")
            self.assertEqual([item["specialist"] for item in response["tasks"]], ["core", "game"])
            queued = SpecialistTaskQueue(database).list_tasks()
            self.assertEqual(len(queued), 2)
            self.assertTrue(all(task.status == "queued" for task in queued))


if __name__ == "__main__":
    unittest.main()
