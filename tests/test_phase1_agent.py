import tempfile
import os
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ai.providers.local_http import (ProviderError, _local_url, OllamaProvider, LocalOpenAICompatibleProvider, provider_from_env)
from ai.runtime.project_tools import ProjectTools, ToolError
from ai.core.agent import DevelopmentAgent, AgentError, MAX_CONTEXT_CHARS, MAX_TOOL_RESULT_CHARS, _trim_context
from ai.__main__ import build_parser, main
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

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
        for url in ("https://127.0.0.1:11434", "http://example.com:11434", "http://127.0.0.1", "http://user:pass@127.0.0.1:11434", "http://127.0.0.1:11434?token=x", "http://127.0.0.1:bad"):
            with self.subTest(url=url), self.assertRaises(ProviderError): _local_url(url)

class ProjectToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tools = ProjectTools(self.root)
    def tearDown(self): self.tmp.cleanup()
    def test_list_files_is_bounded_and_skips_protected_entries(self):
        (self.root / "README.md").write_text("hello", encoding="utf-8")
        (self.root / ".env").write_text("never list", encoding="utf-8")
        (self.root / "secrets").mkdir()
        (self.root / "src").mkdir()
        listing = self.tools.list_files(".")
        self.assertIn("file README.md", listing)
        self.assertIn("dir src", listing)
        self.assertNotIn(".env", listing)
        self.assertNotIn("secrets", listing)

    def test_list_files_rejects_traversal_and_non_directories(self):
        (self.root / "README.md").write_text("hello", encoding="utf-8")
        with self.assertRaises(ToolError):
            self.tools.list_files("../")
        with self.assertRaises(ToolError):
            self.tools.list_files("README.md")

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
    def test_run_python_executes_project_script_and_reports_exit_code(self):
        (self.root / "ai").mkdir()
        os.chmod(self.root, 0o755)
        script = self.root / "ai" / "check.py"
        script.write_text("print('python-ready')\n", encoding="utf-8")
        output = self.tools.run_python("ai/check.py")
        self.assertIn("exit_code=0", output)
        self.assertIn("python-ready", output)

    def test_run_python_reports_nonzero_exit_code(self):
        (self.root / "ai").mkdir()
        os.chmod(self.root, 0o755)
        script = self.root / "ai" / "failing.py"
        script.write_text("raise SystemExit(7)\n", encoding="utf-8")
        output = self.tools.run_python("ai/failing.py")
        self.assertIn("exit_code=7", output)

    def test_run_python_drops_privileges_and_cannot_write_workspace(self):
        import shutil
        if os.environ.get("CI") == "true":
            self.skipTest("CI runner does not permit UID changes; privilege-drop is tested on supported local Linux hosts.")
        if shutil.which("setpriv") is None:
            self.skipTest("Linux setpriv is unavailable.")
        (self.root / "ai").mkdir()
        os.chmod(self.root, 0o755)
        protected = self.root / "protected.txt"
        protected.write_text("safe", encoding="utf-8")
        script = self.root / "ai" / "write_attempt.py"
        script.write_text(
            "from pathlib import Path\n"
            "target = Path(__file__).parents[1] / 'protected.txt'\n"
            "try:\n    target.write_text('changed')\n"
            "except PermissionError:\n    print('write-blocked')\n"
            "else:\n    raise SystemExit(9)\n",
            encoding="utf-8",
        )
        output = self.tools.run_python("ai/write_attempt.py")
        self.assertIn("exit_code=0", output)
        self.assertIn("write-blocked", output)
        self.assertEqual(protected.read_text(encoding="utf-8"), "safe")

    def test_run_python_rejects_non_python_and_missing_files(self):
        (self.root / "ai").mkdir()
        (self.root / "ai" / "note.txt").write_text("not code", encoding="utf-8")
        with self.assertRaises(ToolError):
            self.tools.run_python("ai/note.txt")
        with self.assertRaises(ToolError):
            self.tools.run_python("ai/missing.py")

    def test_fixed_test_command(self):
        with self.assertRaises(ToolError): self.tools.run_tests("rm -rf .")
    def test_game_checks_are_not_available_to_general_tools(self):
        with self.assertRaises(ToolError): self.tools.run_game_checks()

class AgentTests(unittest.TestCase):
    def test_mission_create_and_status_do_not_require_model_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "missions.sqlite3"
            created = StringIO()
            with patch("ai.__main__.provider_from_env", side_effect=AssertionError("model provider must not be loaded")):
                with redirect_stdout(created):
                    self.assertEqual(main([
                        "--mission-create", "--task", "Complete a local test mission",
                        "--mission-db", str(database),
                    ]), 0)
                payload = json.loads(created.getvalue())
                self.assertEqual(payload["status"], "active")
                mission_id = payload["mission_id"]

                status = StringIO()
                with redirect_stdout(status):
                    self.assertEqual(main([
                        "--mission-status", mission_id,
                        "--mission-db", str(database),
                    ]), 0)
                snapshot = json.loads(status.getvalue())
                self.assertEqual(snapshot["mission_id"], mission_id)
                self.assertEqual(snapshot["status"], "active")

    def test_read_then_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("Streamiov")
            p = FakeProvider(['{"tool":"read_file","arguments":{"path":"README.md"}}', '{"final":"Read complete."}'])
            self.assertEqual(DevelopmentAgent(p, tmp).run("Inspect README"), "Read complete.")
    def test_agent_continues_beyond_thirty_model_tool_turns(self):
        class CountingProvider(FakeProvider):
            def __init__(self, outputs):
                super().__init__(outputs)
                self.calls = 0
            def generate(self, **kwargs):
                self.calls += 1
                return super().generate(**kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("Streamiov")
            outputs = ['{"tool":"read_file","arguments":{"path":"README.md"}}' for _ in range(35)]
            outputs.append('{"final":"Completed after thirty-five tool turns."}')
            provider = CountingProvider(outputs)
            self.assertEqual(
                DevelopmentAgent(provider, tmp, max_steps=1).run("Continue until complete"),
                "Completed after thirty-five tool turns.",
            )
            self.assertEqual(provider.calls, 36)
    def test_agent_restores_checkpoint_after_interruption_without_replaying_completed_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_db = root / "agent-checkpoints.sqlite3"
            target = root / "ai" / "checkpointed.py"
            class InterruptingProvider(FakeProvider):
                def generate(self, **kwargs):
                    if not hasattr(self, "called"):
                        self.called = True
                        return super().generate(**kwargs)
                    raise RuntimeError("simulated interruption")
            first = InterruptingProvider([
                '{"tool":"write_file","arguments":{"path":"ai/checkpointed.py","content":"value = 7\\n"}}'
            ])
            agent = DevelopmentAgent(first, root, checkpoint_db=checkpoint_db)
            with self.assertRaises(RuntimeError):
                agent.run("Create checkpointed file", checkpoint_id="mission-task-1")
            self.assertEqual(target.read_text(encoding="utf-8"), "value = 7\n")
            class FinishProvider(FakeProvider):
                def generate(self, **kwargs):
                    self.messages = kwargs["messages"]
                    return super().generate(**kwargs)
            second = FinishProvider(['{"final":"Resumed and completed."}'])
            resumed = DevelopmentAgent(second, root, checkpoint_db=checkpoint_db)
            self.assertEqual(resumed.run("Create checkpointed file", checkpoint_id="mission-task-1"), "Resumed and completed.")
            self.assertIn("ACTION 1 (write_file)", second.messages[-1]["content"])
            self.assertEqual(target.read_text(encoding="utf-8"), "value = 7\n")
            class MustNotRunProvider(FakeProvider):
                def generate(self, **kwargs):
                    raise AssertionError("completed result should be restored from checkpoint")
            recovered_final = DevelopmentAgent(
                MustNotRunProvider([]), root, checkpoint_db=checkpoint_db
            )
            self.assertEqual(
                recovered_final.run("Create checkpointed file", checkpoint_id="mission-task-1"),
                "Resumed and completed.",
            )
            recovered_final.checkpoints.complete("mission-task-1")
    def test_agent_lists_project_files_then_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("Streamiov")
            p = FakeProvider([
                '{"tool":"list_files","arguments":{"path":"."}}',
                '{"final":"Project listing complete."}',
            ])
            self.assertEqual(DevelopmentAgent(p, tmp).run("Inspect project structure"), "Project listing complete.")

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
    def test_invalid_json_gets_one_format_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider(["not json", '{"final":"Recovered safely."}'])
            result = DevelopmentAgent(provider, tmp).run("Do task")
            self.assertEqual(result, "Recovered safely.")

    def test_invalid_json_still_fails_closed_after_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider(["not json", "still not json"])
            with self.assertRaises(AgentError):
                DevelopmentAgent(provider, tmp).run("Do task")
    def test_mixed_tool_and_final_response_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = '{"tool":"read_file","arguments":{"path":"README.md"},"final":"fake"}'
            with self.assertRaises(AgentError): DevelopmentAgent(FakeProvider([response]), tmp).run("Do task")

    def test_specialist_role_sets_expertise_prompt_and_project_wide_write_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            class CapturingProvider(FakeProvider):
                def generate(self, **kwargs):
                    self.system = kwargs["system"]
                    return super().generate(**kwargs)
            provider = CapturingProvider(['{"final":"Review complete."}'])
            agent = DevelopmentAgent(provider, tmp, specialist="game")
            self.assertEqual(agent.run("Plan an original puzzle game."), "Review complete.")
            self.assertIn("SPECIALIST ROLE: Game Developer (game)", provider.system)
            self.assertIn("project files across all modules", provider.system)
            agent.tools.write_file("games/sample.py", "print('original')\n")
            agent.tools.write_file("dist/streamiov-studio-app/sample.js", "console.log('cross-module')\n")
            with self.assertRaises(ToolError):
                agent.tools.write_file("scripts/autonomous/runner.py", "unsafe permission change")

    def test_games_specialist_runs_bounded_local_game_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "games", "releases").mkdir(parents=True)
            Path(tmp, "games", "releases", "README.txt").write_text("No manifest", encoding="utf-8")
            agent = DevelopmentAgent(
                FakeProvider(['{"tool":"run_game_checks","arguments":{}}', '{"final":"Checks complete."}']),
                tmp,
                specialist="game",
            )
            # No manifests is a safe, surfaced tool error rather than executing arbitrary commands.
            self.assertEqual(agent.run("Check the game projects."), "Checks complete.")
            with self.assertRaises(ToolError):
                agent.tools.run_game_checks()

    def test_non_game_agent_cannot_request_game_check_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = DevelopmentAgent(
                FakeProvider(['{"tool":"run_game_checks","arguments":{}}']), tmp, specialist="code"
            )
            with self.assertRaises(AgentError):
                agent.run("Run game checks.")

    def test_studio_specialist_can_write_studio_source_but_not_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = DevelopmentAgent(FakeProvider(['{"final":"Done."}']), tmp, specialist="studio").tools
            tools.write_file("dist/streamiov-studio-app/new-module.js", "module.exports = {};\n")
            with self.assertRaises(ToolError):
                tools.write_file("dist/streamiov-studio-app/secrets/token.json", "secret")


    def test_tool_batch_is_fully_validated_before_first_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "ai", "must_not_exist.py")
            p = FakeProvider([
                '{"tool":"write_file","arguments":{"path":"ai/must_not_exist.py","content":"unsafe partial batch"}}'
                '{"tool":"read_file","arguments":{"path":"README.md","unexpected":"extra"}}'
            ])
            with self.assertRaises(AgentError):
                DevelopmentAgent(p, tmp).run("Do not partially execute invalid batches")
            self.assertFalse(target.exists())

    def test_tool_arguments_reject_non_string_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = FakeProvider(['{"tool":"read_file","arguments":{"path":42}}'])
            with self.assertRaises(AgentError):
                DevelopmentAgent(p, tmp).run("Reject malformed tool arguments")

    def test_context_budget_preserves_original_task_and_newest_turn(self):
        messages = [{"role": "user", "content": "ORIGINAL TASK"}]
        for index in range(20):
            messages.extend([
                {"role": "assistant", "content": f"action-{index}-" + "a" * 3000},
                {"role": "user", "content": f"result-{index}-" + "b" * 3000},
            ])
        trimmed = _trim_context(messages)
        self.assertEqual(trimmed[0]["content"], "ORIGINAL TASK")
        self.assertIn("result-19-", trimmed[-1]["content"])
        self.assertLessEqual(sum(len(message["content"]) for message in trimmed), MAX_CONTEXT_CHARS)

    def test_large_tool_output_is_truncated_before_next_model_call(self):
        class CapturingProvider:
            def __init__(self):
                self.calls = 0
                self.last_messages = None
            def generate(self, **kwargs):
                self.calls += 1
                self.last_messages = kwargs["messages"]
                class Reply:
                    def __init__(self, content): self.content = content
                if self.calls == 1:
                    return Reply('{"tool":"read_file","arguments":{"path":"README.md"}}')
                return Reply('{"final":"bounded output received"}')
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("x" * (MAX_TOOL_RESULT_CHARS + 1000), encoding="utf-8")
            provider = CapturingProvider()
            result = DevelopmentAgent(provider, tmp).run("Read the large file safely")
            self.assertEqual(result, "bounded output received")
            tool_context = provider.last_messages[-1]["content"]
            self.assertIn("tool output truncated at 12,000 characters", tool_context)
            self.assertLess(len(tool_context), MAX_TOOL_RESULT_CHARS + 200)


class CliTests(unittest.TestCase):
    def test_cli_requires_task_and_accepts_workspace_options(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            main([])
        doctor_args = parser.parse_args(["--doctor"])
        self.assertTrue(doctor_args.doctor)
        args = parser.parse_args([
            "--task", "inspect the project",
            "--project-root", "/tmp/streamiov",
            "--max-steps", "5",
        ])
        self.assertEqual(args.task, "inspect the project")
        self.assertEqual(args.project_root, "/tmp/streamiov")
        self.assertEqual(args.max_steps, 5)
        self.assertEqual(args.specialist, "code")
        self.assertEqual(parser.parse_args(["--task", "design a game", "--specialist", "game"]).specialist, "game")

    def test_doctor_cli_returns_success_only_when_provider_is_ready(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        from io import StringIO
        class ReadyProvider:
            def check_ready(self):
                return {"ready": True, "reachable": True, "model_available": True}
        output = StringIO()
        with patch("ai.__main__.provider_from_env", return_value=ReadyProvider()), redirect_stdout(output):
            self.assertEqual(main(["--doctor"]), 0)
        self.assertIn('"ready": true', output.getvalue())


class LocalProviderHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        cls.response_body = {}
        cls.get_response_body = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(cls.get_response_body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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


    def test_ollama_provider_rejects_missing_or_empty_content(self):
        for body in ({"message": {}}, {"message": {"content": ""}}, {"message": "wrong-shape"}):
            with self.subTest(body=body):
                type(self).response_body = body
                provider = OllamaProvider("test-coder", self.base_url)
                with self.assertRaises(ProviderError):
                    provider.generate(system="System", messages=[])

    def test_provider_requires_non_empty_model_name(self):
        with self.assertRaises(ProviderError):
            OllamaProvider(" ", self.base_url)
        with self.assertRaises(ProviderError):
            LocalOpenAICompatibleProvider("", self.base_url)


    def test_ollama_doctor_reports_server_and_model_readiness(self):
        type(self).get_response_body = {"models": [{"name": "other:latest"}, {"name": "test-coder"}]}
        status = OllamaProvider("test-coder", self.base_url).check_ready()
        self.assertTrue(status["reachable"])
        self.assertTrue(status["model_available"])
        self.assertTrue(status["ready"])
        self.assertEqual(status["models_count"], 2)

    def test_ollama_doctor_distinguishes_missing_model_from_offline_server(self):
        type(self).get_response_body = {"models": [{"name": "other:latest"}]}
        missing = OllamaProvider("test-coder", self.base_url).check_ready()
        self.assertTrue(missing["reachable"])
        self.assertFalse(missing["model_available"])
        self.assertFalse(missing["ready"])
        offline = OllamaProvider("test-coder", "http://127.0.0.1:1").check_ready()
        self.assertFalse(offline["reachable"])
        self.assertFalse(offline["ready"])

    def test_openai_compatible_doctor_reads_models_endpoint(self):
        type(self).get_response_body = {"data": [{"id": "local-coder"}, {"id": "other"}]}
        status = LocalOpenAICompatibleProvider("local-coder", self.base_url + "/v1").check_ready()
        self.assertTrue(status["reachable"])
        self.assertTrue(status["model_available"])
        self.assertTrue(status["ready"])
        self.assertEqual(status["models_count"], 2)

    def test_doctor_rejects_malformed_model_list(self):
        type(self).get_response_body = {"unexpected": []}
        status = OllamaProvider("test-coder", self.base_url).check_ready()
        self.assertTrue(status["reachable"])
        self.assertFalse(status["model_available"])
        self.assertFalse(status["ready"])

if __name__ == "__main__":
    unittest.main()
