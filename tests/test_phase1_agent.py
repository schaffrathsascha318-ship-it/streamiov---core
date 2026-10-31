import tempfile
import os
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ai.providers.local_http import (ProviderError, _local_url, OllamaProvider, LocalOpenAICompatibleProvider, provider_from_env)
from ai.runtime.project_tools import ProjectTools, ToolError
from ai.core.agent import DevelopmentAgent, AgentError
from ai.__main__ import build_parser

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
    def test_exact_unique_edit_changes_existing_file(self):
        target = self.root / "ai" / "agent.py"
        target.parent.mkdir()
        target.write_text("before\nold setting\nafter\n", encoding="utf-8")
        result = self.tools.replace_text("ai/agent.py", "old setting", "new setting")
        self.assertIn("one exact match", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "before\nnew setting\nafter\n")
    def test_exact_edit_rejects_missing_or_duplicate_matches_without_change(self):
        target = self.root / "ai" / "agent.py"
        target.parent.mkdir()
        target.write_text("repeat\nrepeat\n", encoding="utf-8")
        with self.assertRaises(ToolError):
            self.tools.replace_text("ai/agent.py", "repeat", "changed")
        with self.assertRaises(ToolError):
            self.tools.replace_text("ai/agent.py", "missing", "changed")
        self.assertEqual(target.read_text(encoding="utf-8"), "repeat\nrepeat\n")
    def test_protected_paths(self):
        for path in ("../outside", ".env", ".env.production", "secrets/admin.json", "config/oauth/token.json", "data/access-token.json", "keys/private-key.pem"):
            with self.subTest(path=path), self.assertRaises(ToolError): self.tools.read_file(path)
    def test_dangling_symlink_is_rejected(self):
        (self.root / "ai").mkdir()
        link = self.root / "ai/dangling.py"
        try:
            os.symlink(self.root / "missing-target.py", link)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable on this platform.")
        with self.assertRaises(ToolError):
            self.tools.write_file("ai/dangling.py", "unsafe")
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
    def test_agent_performs_real_existing_file_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "ai", "agent.py")
            target.parent.mkdir()
            target.write_text("value = 1\n", encoding="utf-8")
            p = FakeProvider([
                '{"tool":"replace_text","arguments":{"path":"ai/agent.py","old_text":"value = 1","new_text":"value = 2"}}',
                '{"final":"Updated the file."}',
            ])
            self.assertEqual(DevelopmentAgent(p, tmp).run("Change value"), "Updated the file.")
            self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")
    def test_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AgentError): DevelopmentAgent(FakeProvider(["not json"]), tmp).run("Do task")
    def test_mixed_tool_and_final_response_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = '{"tool":"read_file","arguments":{"path":"README.md"},"final":"fake"}'
            with self.assertRaises(AgentError): DevelopmentAgent(FakeProvider([response]), tmp).run("Do task")

if __name__ == "__main__": unittest.main()

class CliTests(unittest.TestCase):
    def test_cli_requires_task_and_accepts_workspace_options(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])
        args = parser.parse_args([
            "--task", "inspect the project",
            "--project-root", "/tmp/streamiov",
            "--max-steps", "5",
        ])
        self.assertEqual(args.task, "inspect the project")
        self.assertEqual(args.project_root, "/tmp/streamiov")
        self.assertEqual(args.max_steps, 5)


class LocalProviderHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        cls.response_body = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                cls.requests.append((self.path, payload, self.headers.get("Content-Type")))
                body = json.dumps(cls.response_body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        type(self).requests.clear()

    def test_ollama_provider_sends_chat_payload_and_reads_reply(self):
        type(self).response_body = {"message": {"content": '{"final":"Ollama connected"}'}}
        provider = OllamaProvider("test-coder", self.base_url)
        reply = provider.generate(
            system="Return JSON only.",
            messages=[{"role": "user", "content": "Say hello"}],
        )
        self.assertEqual(reply.content, '{"final":"Ollama connected"}')
        self.assertEqual(reply.provider, "ollama")
        self.assertEqual(reply.model, "test-coder")
        path, payload, content_type = self.requests[0]
        self.assertEqual(path, "/api/chat")
        self.assertEqual(content_type, "application/json")
        self.assertEqual(payload["model"], "test-coder")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "Return JSON only."})
        self.assertEqual(payload["messages"][1]["content"], "Say hello")

    def test_openai_compatible_provider_sends_chat_completion_payload(self):
        type(self).response_body = {"choices": [{"message": {"content": '{"final":"Local server connected"}'}}]}
        provider = LocalOpenAICompatibleProvider("local-code-model", self.base_url + "/v1")
        reply = provider.generate(system="System", messages=[{"role": "user", "content": "Hello"}])
        self.assertEqual(reply.content, '{"final":"Local server connected"}')
        self.assertEqual(reply.provider, "local-openai-compatible")
        path, payload, _ = self.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(payload["model"], "local-code-model")
        self.assertEqual(payload["messages"][0]["role"], "system")

    def test_openai_compatible_provider_rejects_malformed_response(self):
        type(self).response_body = {"choices": []}
        provider = LocalOpenAICompatibleProvider("local-code-model", self.base_url + "/v1")
        with self.assertRaises(ProviderError):
            provider.generate(system="System", messages=[])

    def test_environment_selects_only_local_providers(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {
            "STREAMIOV_MODEL_PROVIDER": "ollama",
            "STREAMIOV_MODEL": "test-model",
            "STREAMIOV_MODEL_URL": self.base_url,
        }):
            self.assertIsInstance(provider_from_env(), OllamaProvider)
        with patch.dict(os.environ, {
            "STREAMIOV_MODEL_PROVIDER": "openai-compatible-local",
            "STREAMIOV_MODEL": "test-model",
            "STREAMIOV_MODEL_URL": self.base_url + "/v1",
        }):
            self.assertIsInstance(provider_from_env(), LocalOpenAICompatibleProvider)
        with patch.dict(os.environ, {"STREAMIOV_MODEL_PROVIDER": "cloud"}):
            with self.assertRaises(ProviderError):
                provider_from_env()
