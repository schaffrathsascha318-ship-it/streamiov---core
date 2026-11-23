import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools, ToolError, _locked_path, _process_lock_path


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
        path = self.root / "process-shared.txt"
        ready = self.root / "holder-ready"
        acquired = self.root / "contender-acquired"
        helper = self.root / "lock_worker.py"
        helper.write_text(
            "import sys, time\\n"
            "from pathlib import Path\\n"
            "from ai.runtime.project_tools import _locked_path\\n"
            "mode, target, marker = sys.argv[1:]\\n"
            "with _locked_path(Path(target), owner={\\"task_id\\": mode}):\\n"
            "    Path(marker).write_text(\\"locked\\", encoding=\\"utf-8\\")\\n"
            "    if mode == \\"process-holder\\":\\n"
            "        while True: time.sleep(1)\\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        repo_root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
        holder = subprocess.Popen(
            [sys.executable, str(helper), "process-holder", str(path), str(ready)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=env,
        )
        contender = None

        def wait_for_marker(marker: Path, process: subprocess.Popen, timeout: float, message: str):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if marker.exists():
                    return
                if process.poll() is not None:
                    _, error = process.communicate()
                    self.fail(f"{message}; worker exited {process.returncode}: {error}")
                time.sleep(0.05)
            self.fail(message)

        try:
            wait_for_marker(ready, holder, 8, "first process did not acquire the OS lock")
            contender = subprocess.Popen(
                [sys.executable, str(helper), "process-contender", str(path), str(acquired)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=env,
            )
            time.sleep(0.3)
            self.assertFalse(acquired.exists(), "second process entered while the first lock was held")
            holder.terminate()
            holder.wait(timeout=5)
            wait_for_marker(acquired, contender, 8, "OS lock was not released when the holder process died")
            contender.wait(timeout=5)
            lock_path = _process_lock_path(str(path.resolve()))
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["task_id"], "process-contender")
        finally:
            if holder.poll() is None:
                holder.terminate()
            holder.wait(timeout=5)
            if contender is not None:
                if contender.poll() is None:
                    contender.terminate()
                contender.wait(timeout=5)

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
