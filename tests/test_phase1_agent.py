import tempfile
import unittest
from pathlib import Path
from ai.providers.local_http import ProviderError, _local_url
from ai.runtime.project_tools import ProjectTools, ToolError
from ai.core.agent import DevelopmentAgent, AgentError

class FakeProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
    def generate(self, **kwargs):
        class Reply:
            def __init__(self, content): self.content = content
        return Reply(next(self.outputs))

class ProviderTests(unittest.TestCase):
    def test_loopback_only(self):
        self.assertEqual(_local_url("http://127.0.0.1:11434/"), "http://127.0.0.1:11434")
        for url in ("https://127.0.0.1:11434", "http://example.com:11434", "http://127.0.0.1"):
            with self.subTest(url=url), self.assertRaises(ProviderError): _local_url(url)

class ProjectToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tools = ProjectTools(self.root)
    def tearDown(self): self.tmp.cleanup()
    def test_read_create(self):
        (self.root / "README.md").write_text("hello", encoding="utf-8")
        self.assertEqual(self.tools.read_file("README.md"), "hello")
        self.tools.write_file("ai/new.py", "print('ok')")
        self.assertEqual((self.root / "ai/new.py").read_text(), "print('ok')")
    def test_protected_paths(self):
        for path in ("../outside", ".env", "secrets/admin.json", "config/oauth/token.json"):
            with self.subTest(path=path), self.assertRaises(ToolError): self.tools.read_file(path)
    def test_no_overwrite_or_unapproved_write(self):
        with self.assertRaises(ToolError): self.tools.write_file("core/app.py", "x")
        (self.root / "ai").mkdir()
        (self.root / "ai/existing.py").write_text("safe")
        with self.assertRaises(ToolError): self.tools.write_file("ai/existing.py", "overwrite")
    def test_fixed_test_command(self):
        with self.assertRaises(ToolError): self.tools.run_tests("rm -rf .")

class AgentTests(unittest.TestCase):
    def test_read_then_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("Streamiov")
            p = FakeProvider(['{"tool":"read_file","arguments":{"path":"README.md"}}', '{"final":"Read complete."}'])
            self.assertEqual(DevelopmentAgent(p, tmp).run("Inspect README"), "Read complete.")
    def test_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AgentError): DevelopmentAgent(FakeProvider(["not json"]), tmp).run("Do task")

if __name__ == "__main__": unittest.main()
