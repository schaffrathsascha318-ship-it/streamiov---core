import threading
import unittest

from ai.runtime.task_queue import WorkerExecution
from ai.runtime.worker_service import run_worker_loop


class FakeWorker:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def run_once(self):
        self.calls += 1
        return next(self.results, None)


class WorkerServiceTests(unittest.TestCase):
    def test_worker_loop_processes_bounded_number_of_tasks(self):
        worker = FakeWorker([
            WorkerExecution("one", "succeeded", result="ok"),
            WorkerExecution("two", "succeeded", result="ok"),
        ])
        output = []
        code = run_worker_loop(worker, threading.Event(), max_tasks=2, emit=output.append)
        self.assertEqual(code, 0)
        self.assertEqual(worker.calls, 2)
        self.assertEqual(len(output), 2)

    def test_worker_loop_reports_failure_and_continues_independent_tasks(self):
        worker = FakeWorker([
            WorkerExecution("one", "failed", error="failed"),
            WorkerExecution("two", "succeeded", result="independent"),
        ])
        output = []
        code = run_worker_loop(worker, threading.Event(), max_tasks=2, emit=output.append)
        self.assertEqual(code, 1)
        self.assertEqual(worker.calls, 2)
        self.assertIn('"task_id": "two"', output[1])

    def test_worker_loop_stops_cooperatively_when_idle(self):
        stop = threading.Event()
        class IdleWorker:
            calls = 0
            def run_once(self):
                self.calls += 1
                stop.set()
                return None
        worker = IdleWorker()
        code = run_worker_loop(worker, stop, poll_seconds=1, emit=lambda _line: None)
        self.assertEqual(code, 0)
        self.assertEqual(worker.calls, 1)

    def test_worker_loop_rejects_unsafe_poll_and_task_limits(self):
        worker = FakeWorker([])
        with self.assertRaises(ValueError):
            run_worker_loop(worker, threading.Event(), poll_seconds=0)
        with self.assertRaises(ValueError):
            run_worker_loop(worker, threading.Event(), max_tasks=-1)


if __name__ == "__main__":
    unittest.main()
