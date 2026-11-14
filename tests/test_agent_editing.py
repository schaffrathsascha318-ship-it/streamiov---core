import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools, ToolError
from ai.core.agent import DevelopmentAgent
from ai.specialists import get_specialist


class FakeProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def generate(self, **kwargs):
        class Reply:
            def __init__(self, content):
                self.content = content
        return Reply(next(self.outputs))


class SafeEditingTests(unittest.TestCase):
    def test_full_edit_creates_exact_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "ai" / "module.py"
            target.parent.mkdir()
            target.write_text("old content\\n", encoding="utf-8")
            tools = ProjectTools(root)
            info = tools.file_info("ai/module.py")
            digest = info.split("SHA-256: ", 1)[1]
            result = tools.edit_file("ai/module.py", digest, "new content\\n")
            self.assertEqual(target.read_text(), "new content\\n")
            self.assertIn("Backup:", result)
            backups = list((root / ".streamiov-recovery" / "backups").glob("*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "old content\\n")

    def test_stale_hash_refuses_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "ai" / "module.py"
            target.parent.mkdir()
            target.write_text("changed meanwhile", encoding="utf-8")
            tools = ProjectTools(root)
            with self.assertRaises(ToolError):
                tools.edit_file("ai/module.py", hashlib.sha256(b"old").hexdigest(), "replacement")
            self.assertEqual(target.read_text(), "changed meanwhile")

    def test_full_edit_respects_specialist_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "core" / "app.py"
            target.parent.mkdir()
            target.write_text("old", encoding="utf-8")
            tools = ProjectTools(root, writable_prefixes=("ai/",))
            digest = hashlib.sha256(b"old").hexdigest()
            with self.assertRaises(ToolError):
                tools.edit_file("core/app.py", digest, "new")
            self.assertEqual(target.read_text(), "old")

    def test_chief_role_is_registered_and_has_project_scope(self):
        definition = get_specialist("chief")
        self.assertIn("**", definition.writable_prefixes)

    def test_agent_can_inspect_and_edit_existing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ai" / "module.py"
            target.parent.mkdir()
            target.write_text("value = 1\n", encoding="utf-8")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()

            provider = FakeProvider([
                '{"tool":"file_info","arguments":{"path":"ai/module.py"}}',
                json.dumps({"tool": "edit_file", "arguments": {"path": "ai/module.py", "expected_sha256": digest, "content": "value = 2\n"}}),
                '{"final":"Edited and verified."}',
                '{"tool":"run_tests","arguments":{"command":"python -m unittest discover -s tests"}}',
                '{"final":"Edited and verified."}',
            ])

            agent = DevelopmentAgent(provider, tmp)
            agent.tools.run_tests = lambda command: "exit_code=0\nOK"

            result = agent.run("Update the value in the module.")
            self.assertEqual(result, "Edited and verified.")
            self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")

