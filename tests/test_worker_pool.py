import json
import threading
import time
import unittest

from ai.runtime.task_queue import WorkerExecution
from ai.runtime.worker_pool import run_worker_pool


class SharedFakeQueue:
    def __init__(self, count):
        self.lock = threading.Lock()
        self.remaining = list(range(count))
        self.active = 0
        self.max_active = 0
        self.worker_ids = []

    def worker(self, worker_id):
        self.worker_ids.append(worker_id)
        queue = self

        class Worker:
            def run_once(self):
                with queue.lock:
                    if not queue.remaining:
                        return None
                    task = queue.remaining.pop(0)
                    queue.active += 1
                    queue.max_active = max(queue.max_active, queue.active)
                time.sleep(0.03)
                with queue.lock:
                    queue.active -= 1
                return WorkerExecution(str(task), "succeeded", result="ok")
        return Worker()


class WorkerPoolTests(unittest.TestCase):
    def test_workers_execute_in_parallel_and_have_unique_ids(self):
        queue = SharedFakeQueue(6)
        output = []
        code = run_worker_pool(queue.worker, threading.Event(), workers=3, max_tasks=6, emit=output.append)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(queue.max_active, 2)
        self.assertEqual(len(set(queue.worker_ids)), 3)
        self.assertEqual(len([json.loads(line) for line in output]), 6)

    def test_global_max_tasks_is_not_exceeded(self):
        queue = SharedFakeQueue(20)
        output = []
        run_worker_pool(queue.worker, threading.Event(), workers=4, max_tasks=5, emit=output.append)
        self.assertEqual(len(output), 5)

    def test_failed_task_is_reported_without_stopping_other_workers(self):
        class Worker:
            def __init__(self):
                self.calls = 0
            def run_once(self):
                self.calls += 1
                if self.calls == 1:
                    return WorkerExecution("bad", "failed", error="test")
                if self.calls == 2:
                    return WorkerExecution("good", "succeeded", result="ok")
                return None
        workers = []
        def factory(worker_id):
            worker = Worker()
            workers.append(worker)
            return worker
        output = []
        code = run_worker_pool(factory, threading.Event(), workers=1, max_tasks=2, emit=output.append)
        self.assertEqual(code, 1)
        self.assertEqual(len(output), 2)

    def test_invalid_worker_bounds_are_rejected(self):
        with self.assertRaises(ValueError):
            run_worker_pool(lambda _id: None, threading.Event(), workers=0)
        with self.assertRaises(ValueError):
            run_worker_pool(lambda _id: None, threading.Event(), workers=9)


if __name__ == "__main__":
    unittest.main()
