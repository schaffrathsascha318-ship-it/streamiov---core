import tempfile
import threading
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools, ToolError, _locked_path


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

    def test_independent_processes_cannot_overwrite_same_file_edit(self):
        import subprocess
        import sys

        path = self.root / "process-shared.txt"
        path.write_text("base\\n", encoding="utf-8")
        script = (
            "import sys; from pathlib import Path; "
            "from ai.runtime.project_tools import ProjectTools, ToolError; "
            "tools=ProjectTools(Path(sys.argv[1]), full_project_development=True); "
            "try_result=None; "
            "\\ntry: try_result=tools.replace_text('process-shared.txt','base',sys.argv[2])"
            "\\nexcept ToolError as exc: print('REJECTED:'+str(exc))"
            "\\nelse: print('UPDATED:'+try_result)"
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(self.root), value],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for value in ("process-a", "process-b")
        ]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            results.append(stdout.strip())
        final = path.read_text(encoding="utf-8")
        self.assertIn(final, {"process-a\\n", "process-b\\n"})
        self.assertEqual(sum(item.startswith("UPDATED:") for item in results), 1)
        self.assertEqual(sum(item.startswith("REJECTED:") for item in results), 1)

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
