import json
import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools, ToolError, _locked_path, _process_lock_path


def _hold_process_lock(path: str, ready, release) -> None:
    with _locked_path(Path(path), owner={"task_id": "process-holder"}):
        ready.set()
        release.wait(20)


def _wait_for_process_lock(path: str, acquired) -> None:
    with _locked_path(Path(path), owner={"task_id": "process-contender"}):
        acquired.set()


class ProjectToolsConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.first = ProjectTools(self.root, full_project_development=True)
        self.second = ProjectTools(self.root, full_project_development=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_same_file_edits_are_serialized_and_stale_edit_is_rejected(self):
        path = self.root / "shared.txt"
        path.write_text("base\n", encoding="utf-8")
        barrier = threading.Barrier(2)
        outcomes = []
        outcome_lock = threading.Lock()

        def edit(tools, replacement):
            barrier.wait(timeout=3)
            try:
                result = tools.replace_text("shared.txt", "base", replacement)
            except ToolError as exc:
                result = f"rejected:{exc}"
            with outcome_lock:
                outcomes.append(result)

        threads = [
            threading.Thread(target=edit, args=(self.first, "worker-a")),
            threading.Thread(target=edit, args=(self.second, "worker-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        final = path.read_text(encoding="utf-8")
        self.assertIn(final, {"worker-a\n", "worker-b\n"})
        self.assertEqual(sum(item.startswith("Updated ") for item in outcomes), 1)
        self.assertEqual(sum(item.startswith("rejected:") for item in outcomes), 1)

    def test_os_file_lock_serializes_separate_processes_and_recovers_after_crash(self):
        context = multiprocessing.get_context("spawn")
        path = str(self.root / "process-shared.txt")
        ready = context.Event()
        release = context.Event()
        acquired = context.Event()
        holder = context.Process(target=_hold_process_lock, args=(path, ready, release))
        contender = context.Process(target=_wait_for_process_lock, args=(path, acquired))
        holder.start()
        try:
            self.assertTrue(ready.wait(8), "first process did not acquire the OS lock")
            contender.start()
            self.assertFalse(acquired.wait(0.3), "second process entered while the first lock was held")
            holder.terminate()
            holder.join(5)
            self.assertFalse(holder.is_alive())
            self.assertTrue(acquired.wait(8), "OS lock was not released when the holder process died")
            contender.join(5)
            self.assertFalse(contender.is_alive())
            lock_path = _process_lock_path(str(Path(path).resolve()))
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["task_id"], "process-contender")
        finally:
            release.set()
            if holder.is_alive():
                holder.terminate()
            holder.join(5)
            if contender.is_alive():
                contender.terminate()
            contender.join(5)

    def test_distinct_file_locks_allow_independent_workers_to_overlap(self):
        barrier = threading.Barrier(2, timeout=3)
        errors = []

        def hold(path):
            try:
                with _locked_path(self.root / path):
                    barrier.wait()
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=hold, args=("one.txt",)),
            threading.Thread(target=hold, args=("two.txt",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_concurrent_create_never_overwrites_the_winning_file(self):
        barrier = threading.Barrier(2)
        outcomes = []
        outcome_lock = threading.Lock()

        def create(tools, value):
            barrier.wait(timeout=3)
            try:
                result = tools.write_file("new.txt", value)
            except ToolError as exc:
                result = f"rejected:{exc}"
            with outcome_lock:
                outcomes.append(result)

        threads = [
            threading.Thread(target=create, args=(self.first, "from-a")),
            threading.Thread(target=create, args=(self.second, "from-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        self.assertIn((self.root / "new.txt").read_text(encoding="utf-8"), {"from-a", "from-b"})
        self.assertEqual(sum(item.startswith("Created ") for item in outcomes), 1)
        self.assertEqual(sum(item.startswith("rejected:") for item in outcomes), 1)

    def test_atomic_replace_readers_never_observe_partial_content(self):
        path = self.root / "large.txt"
        old = "A" * 80_000
        new = "B" * 80_000
        path.write_text(old, encoding="utf-8")
        started = threading.Event()
        observed = []
        errors = []

        def reader():
            started.set()
            for _ in range(100):
                value = self.second.read_file("large.txt")
                if value not in {old, new}:
                    errors.append("partial or mixed file contents observed")
                    return
                observed.append(value)

        thread = threading.Thread(target=reader)
        thread.start()
        started.wait(timeout=2)
        self.first.replace_text("large.txt", old, new)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(observed)
        self.assertIn(path.read_text(encoding="utf-8"), {old, new})


if __name__ == "__main__":
    unittest.main()
