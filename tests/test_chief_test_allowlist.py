"""Regression checks for the fixed Chief test-command allowlist."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.runtime.project_tools import NODE_TEST_COMMANDS, TEST_COMMANDS, ProjectTools, ToolError


ALLOWED_COMMANDS = {
    "python -m unittest discover -s tests",
    "node --test tests/test_cloudflare_ai_worker.mjs",
    "python scripts/verify-cloudflare-config.py",
    "node scripts/release-signing.mjs verify-release",
}


class ChiefTestAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tools = ProjectTools(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_documented_commands_are_the_complete_allowlist(self):
        self.assertEqual(set(TEST_COMMANDS) | set(NODE_TEST_COMMANDS), ALLOWED_COMMANDS)

    def test_allowlisted_commands_map_to_fixed_argv_without_shell_text(self):
        for command, argv in {**TEST_COMMANDS, **NODE_TEST_COMMANDS}.items():
            with self.subTest(command=command):
                self.assertIsInstance(argv, list)
                self.assertTrue(argv)
                self.assertTrue(all(isinstance(part, str) for part in argv))
                self.assertNotIn(command, ("", " "))
                self.assertFalse(any(character in command for character in ";&|`$><"))

    def test_run_tests_uses_the_fixed_argv_for_each_documented_command(self):
        completed = subprocess.CompletedProcess(["fixed"], 0, "OK", "")
        which = lambda name: "/usr/bin/bwrap" if name == "bwrap" else "/usr/bin/node"
        with patch("ai.runtime.project_tools.shutil.which", side_effect=which), \
             patch("ai.runtime.project_tools.subprocess.run", return_value=completed) as run:
            for command in sorted(ALLOWED_COMMANDS):
                with self.subTest(command=command):
                    output = self.tools.run_tests(command)
                    self.assertTrue(output.startswith("exit_code=0"))
                    argv = run.call_args.args[0]
                    self.assertEqual(argv[0], "/usr/bin/bwrap")
                    self.assertIn("--ro-bind", argv)
                    self.assertIn("--unshare-net", argv)
                    fixed = argv[argv.index("--") + 1]
                    self.assertEqual(fixed, "/usr/bin/node" if command.startswith("node ") else sys.executable)
        self.assertEqual(run.call_count, len(ALLOWED_COMMANDS))

    def test_shell_altered_and_unhashable_commands_are_rejected(self):
        rejected = [
            "rm -rf .",
            "python -m unittest discover -s tests; rm -rf .",
            "node --test tests/test_cloudflare_ai_worker.mjs && true",
            "python scripts/verify-cloudflare-config.py --deploy",
            "node scripts/release-signing.mjs generate-key",
            "",
            None,
            ["python"],
        ]
        with patch("ai.runtime.project_tools.subprocess.run") as run:
            for command in rejected:
                with self.subTest(command=command), self.assertRaises(ToolError):
                    self.tools.run_tests(command)
        run.assert_not_called()

    def test_node_commands_fail_closed_without_node(self):
        which = lambda name: "/usr/bin/bwrap" if name == "bwrap" else None
        with patch("ai.runtime.project_tools.shutil.which", side_effect=which), \
             patch("ai.runtime.project_tools.subprocess.run") as run:
            with self.assertRaisesRegex(ToolError, "Node.js is required"):
                self.tools.run_tests("node --test tests/test_cloudflare_ai_worker.mjs")
        run.assert_not_called()

    def test_tests_fail_closed_without_bubblewrap(self):
        which = lambda name: None if name == "bwrap" else "/usr/bin/node"
        with patch("ai.runtime.project_tools.shutil.which", side_effect=which), \
             patch("ai.runtime.project_tools.subprocess.run") as run:
            with self.assertRaisesRegex(ToolError, "unsandboxed test execution is disabled"):
                self.tools.run_tests("python -m unittest discover -s tests")
        run.assert_not_called()

    def test_fast_allowlisted_checks_execute_for_real(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed in this environment.")
        if shutil.which("bwrap") is None:
            self.skipTest("bubblewrap is not installed in this environment.")
        root = Path(__file__).resolve().parents[1]
        tools = ProjectTools(root)
        for command in (
            "node --test tests/test_cloudflare_ai_worker.mjs",
            "python scripts/verify-cloudflare-config.py",
            "node scripts/release-signing.mjs verify-release",
        ):
            with self.subTest(command=command):
                output = tools.run_tests(command)
                self.assertTrue(output.startswith("exit_code=0"), output[:800])

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is not installed in this environment.")
    def test_sandboxed_tests_cannot_read_the_parent_environment(self):
        with tempfile.TemporaryDirectory(dir="/var/tmp") as tmp:
            root = Path(tmp)
            tests = root / "tests"
            tests.mkdir()
            leak_test = tests / "test_parent_environment.py"
            leak_test.write_text(
                'import os\n'
                'import unittest\n'
                'class ParentEnvironmentTests(unittest.TestCase):\n'
                '    def test_parent_environment_is_not_readable(self):\n'
                '        try:\n'
                '            with open("/proc/%d/environ" % os.getppid(), "rb") as handle:\n'
                '                data = handle.read()\n'
                '        except OSError:\n'
                '            data = b""\n'
                '        self.assertNotIn(b"STREAMIOV_TEST_SECRET", data)\n',
                encoding="utf-8",
            )
            os.chmod(root, 0o755)
            os.chmod(tests, 0o755)
            os.chmod(leak_test, 0o644)
            tools = ProjectTools(root)
            with patch.dict(os.environ, {"STREAMIOV_TEST_SECRET": "must-not-leak"}):
                output = tools.run_tests("python -m unittest discover -s tests")
            self.assertTrue(output.startswith("exit_code=0"), output[:800])


if __name__ == "__main__":
    unittest.main()
