"""Regression tests for the specialist model-to-tool action protocol."""
from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai.core.agent import (
    AgentError,
    DevelopmentAgent,
    _parse_actions,
    _fit_provider_messages,
    _validate_tool_action,
    AgentCheckpointStore,
)
from ai.core.verification_evidence import VerificationReportError, validate_verification_report
from ai.providers.base import ModelReply


class SequenceProvider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.messages = []

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        self.calls += 1
        self.messages.append([dict(message) for message in messages])
        if not self.responses:
            raise AssertionError("Unexpected extra model request.")
        return ModelReply(self.responses.pop(0), "test", "fixture")


class SpecialistActionProtocolTests(unittest.TestCase):

    def test_system_prompt_only_offers_game_checks_to_eligible_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            code = DevelopmentAgent(SequenceProvider([]), directory, specialist="code")
            game = DevelopmentAgent(SequenceProvider([]), directory, specialist="ai_games_agent")
            testing = DevelopmentAgent(SequenceProvider([]), directory, specialist="testing")
        self.assertNotIn("run_game_checks", code.system_prompt)
        self.assertIn("run_game_checks", game.system_prompt)
        self.assertIn("run_game_checks", testing.system_prompt)

    def test_provider_action_budget_stops_unbounded_recovery_loops(self):
        provider = SequenceProvider(
            '{"tool":"unknown_tool","arguments":{}}',
            '{"tool":"unknown_tool","arguments":{}}',
        )
        provider.max_actions = 2
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            with self.assertRaisesRegex(AgentError, "provider action budget"):
                agent.run("inspect the repository")
        self.assertEqual(provider.calls, 2)

    def test_old_checkpoint_schema_migrates_retry_and_final_columns_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory, "old.sqlite3")
            task = "legacy task"
            import hashlib
            digest = hashlib.sha256(task.encode("utf-8")).hexdigest()
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("""CREATE TABLE agent_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY, task_hash TEXT NOT NULL,
                    specialist TEXT NOT NULL, messages_json TEXT NOT NULL,
                    pending_actions_json TEXT NOT NULL DEFAULT '[]',
                    next_action_index INTEGER NOT NULL DEFAULT 0,
                    results_json TEXT NOT NULL DEFAULT '[]', updated_at REAL NOT NULL
                )""")
                db.execute("INSERT INTO agent_checkpoints VALUES(?,?,?,?,?,?,?,?)",
                    ("legacy", digest, "code", json.dumps([{"role":"user","content":task}]),
                     "[]", 0, "[]", 1.0))
            store = AgentCheckpointStore(database)
            state = store.load("legacy", task, "code")
            self.assertEqual(state["format_retries"], 0)
            self.assertIsNone(state["final_result"])
            self.assertIsNone(state["in_flight_action_index"])
            with closing(sqlite3.connect(database)) as db, db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(agent_checkpoints)")}
                self.assertTrue({"format_retries", "final_result", "in_flight_action_index", "checkpoint_version"} <= columns)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM agent_checkpoints").fetchone()[0], 1)

    def test_successful_tool_evidence_survives_checkpoint_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory, "checkpoints.sqlite3")
            task = "inspect and resume"
            store = AgentCheckpointStore(database)
            state = {
                "messages": [{"role": "user", "content": task}],
                "pending_actions": [],
                "next_action_index": 0,
                "results": [],
                "successful_actions": [{"tool": "list_files", "result": "README.md"}],
                "format_retries": 0,
                "final_result": None,
                "in_flight_action_index": None,
                "checkpoint_version": 1,
            }
            store.save("evidence", task, "research", state)
            resumed = store.load("evidence", task, "research")
            self.assertEqual(resumed["successful_actions"], state["successful_actions"])

    def test_interrupted_action_is_not_replayed_and_checkpoint_recovers_through_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory, "checkpoints.sqlite3")
            task = "create a file"
            store = AgentCheckpointStore(database)
            state = {
                "messages": [{"role": "user", "content": task}],
                "pending_actions": [{"tool": "write_file", "arguments": {"path": "created.txt", "content": "x"}}],
                "next_action_index": 0, "results": [], "format_retries": 0,
                "final_result": None, "in_flight_action_index": 0, "checkpoint_version": 1,
            }
            store.save("crash", task, "code", state)
            provider = SequenceProvider('{"tool":"list_files","arguments":{"path":"."}}', '{"final":"Inspected the workspace; no file was created."}')
            agent = DevelopmentAgent(provider, directory, specialist="code", checkpoint_db=database)
            result = agent.run(task, checkpoint_id="crash")
            self.assertIn("Inspected the workspace", result)
            self.assertEqual(provider.calls, 2)
            recovery = next(
                message["content"]
                for call in provider.messages
                for message in call
                if "CRASH RECOVERY" in message["content"]
            )
            self.assertIn("CRASH RECOVERY", recovery)
            self.assertIn("UNKNOWN", recovery)
            self.assertIn("NEVER replay", recovery)
            self.assertFalse(Path(directory, "created.txt").exists())
            resumed = store.load("crash", task, "code")
            self.assertIsNone(resumed["in_flight_action_index"])
            self.assertEqual(resumed["pending_actions"], [])

    def test_parses_single_object_array_and_fenced_json(self):
        action = {"tool": "list_files", "arguments": {"path": "."}}
        self.assertEqual(_parse_actions('{"tool":"list_files","arguments":{"path":"."}}'), [action])
        self.assertEqual(_parse_actions('[{"tool":"list_files","arguments":{"path":"."}}]'), [action])
        fenced = "```json\n" + '{"tool":"list_files","arguments":{"path":"."}}' + "\n```"
        self.assertEqual(_parse_actions(fenced), [action])

    def test_provider_context_collapses_repeated_legacy_checkpoint_results(self):
        original = {"role": "user", "content": "original task"}
        repeated = {"role": "user", "content": "ACTION 1 (list_files):\\nfile README.md"}
        messages = [original, repeated, repeated, repeated]
        fitted = _fit_provider_messages("system", messages)
        self.assertEqual(fitted, [original, {"role": "user", "content": "file README.md"}])

    def test_provider_context_drops_synthetic_assistant_tool_summaries(self):
        original = {"role": "user", "content": "original task"}
        synthetic = {"role": "assistant", "content": "Previously requested tools: list_files"}
        results = {"role": "user", "content": "TOOL RESULTS for the actions you already requested."}
        fitted = _fit_provider_messages("system", [original, synthetic, results])
        self.assertEqual(fitted, [original, results])
        self.assertNotIn("Previously requested tools", [message["content"] for message in fitted])

    def test_rejects_leading_trailing_prose_and_truncated_json(self):
        invalid = (
            'Here is the action: {"tool":"list_files","arguments":{"path":"."}}',
            '{"tool":"list_files","arguments":{"path":"."}} done',
            '{"tool":"list_files","arguments":',
        )
        for response in invalid:
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    _parse_actions(response)

    def test_rejects_provider_tool_call_envelopes_as_non_protocol_actions(self):
        envelope = {"tool_calls": [{"type": "function", "function": {"name": "list_files", "arguments": '{"path":"."}'}}]}
        with self.assertRaises(AgentError):
            _validate_tool_action(envelope)

    def test_valid_array_actions_execute_before_final_response(self):
        provider = SequenceProvider(
            '[{"tool":"write_file","arguments":{"path":"ai/created.py","content":"safe"}}]',
            '{"final":"created"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            result = agent.run("Create created.txt with the word safe.")
            self.assertIn("created", result)
            self.assertEqual(result, "created")
            self.assertEqual(Path(directory, "ai", "created.py").read_text(encoding="utf-8"), "safe")
        self.assertEqual(provider.calls, 2)

    def test_schema_invalid_action_is_corrected_without_execution(self):
        provider = SequenceProvider(
            '{"tool":"write_file","arguments":{"path":"blocked.txt","content":"bad","extra":"no"}}',
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"final":"no action executed"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertIn("no action executed", agent.run("Do not create blocked.txt."))
            self.assertFalse(Path(directory, "blocked.txt").exists())
        self.assertEqual(provider.calls, 3)
        correction = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        self.assertIn("allowed keys are ['content', 'path']", correction)
        self.assertIn("unexpected keys are ['extra']", correction)
        self.assertIn("Never repeat a rejected object verbatim", correction)
        self.assertNotIn("run_game_checks", correction)

    def test_read_file_offset_and_length_are_rejected_with_actionable_schema_feedback(self):
        invalid = json.dumps({
            "tool": "read_file",
            "arguments": {"path": "README.md", "offset": "400", "length": "150"},
        })
        provider = SequenceProvider(invalid, '{"tool":"list_files","arguments":{"path":"."}}', '{"final":"corrected"}')
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertIn("corrected", agent.run("Read the README safely."))
        diagnostic = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        self.assertIn("allowed keys are ['path']", diagnostic)
        self.assertIn("unexpected keys are ['length', 'offset']", diagnostic)

    def test_final_without_successful_tool_evidence_is_rejected(self):
        provider = SequenceProvider('{"final":"I am done"}')
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="research")
            with self.assertRaisesRegex(AgentError, "without at least one successfully executed project tool"):
                agent.run("Research the existing project state.")

    def test_successful_read_only_inspection_counts_as_research_evidence(self):
        provider = SequenceProvider('{"tool":"list_files","arguments":{"path":"."}}', '{"final":"Inspected the project."}')
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory, "agent-checkpoints.sqlite3")
            agent = DevelopmentAgent(provider, directory, specialist="research", checkpoint_db=database)
            result = agent.run("Inspect the project.", checkpoint_id="research-inspection")
            self.assertEqual(result, "Inspected the project.")
            evidence = AgentCheckpointStore(database).load(
                "research-inspection", "Inspect the project.", "research"
            )["successful_actions"]
            self.assertEqual([item["tool"] for item in evidence], ["list_files"])

    def test_malformed_replies_have_bounded_corrections_per_run(self):
        provider = SequenceProvider("not json", "still not json", "still invalid", "invalid again")
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            with self.assertRaisesRegex(AgentError, "bounded corrections"):
                agent.run("Perform a harmless task.")
        self.assertEqual(provider.calls, 4)


    def test_adjacent_legacy_objects_are_parsed_as_one_ordered_action_batch(self):
        first = {"tool": "list_files", "arguments": {"path": "."}}
        second = {"tool": "read_file", "arguments": {"path": "README.md"}}
        self.assertEqual(
            _parse_actions(json.dumps(first) + "\n" + json.dumps(second)),
            [first, second],
        )

    def test_invalid_later_action_prevents_every_earlier_batch_side_effect(self):
        provider = SequenceProvider(
            json.dumps([
                {"tool": "write_file", "arguments": {"path": "must-not-exist.txt", "content": "unsafe partial batch"}},
                {"tool": "write_file", "arguments": {"path": "also-invalid.txt", "content": "x", "unexpected": "field"}},
            ]),
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"final":"rejected the entire batch before execution"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            result = agent.run("Do not create either file; reject malformed action batches atomically.")
            self.assertIn("rejected the entire batch before execution", result)
            self.assertFalse(Path(directory, "must-not-exist.txt").exists())
            self.assertFalse(Path(directory, "also-invalid.txt").exists())
        self.assertEqual(provider.calls, 3)
        correction = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        self.assertIn("unexpected keys are ['unexpected']", correction)

    def test_mixed_final_and_tool_actions_are_rejected_before_execution(self):
        provider = SequenceProvider(
            json.dumps([
                {"tool": "write_file", "arguments": {"path": "must-not-exist.txt", "content": "x"}},
                {"final": "must not complete a mixed batch"},
            ]),
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"final":"mixed batch rejected"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertIn("mixed batch rejected", agent.run("Reject a mixed final/action response."))
            self.assertFalse(Path(directory, "must-not-exist.txt").exists())
        self.assertEqual(provider.calls, 3)

    def test_final_verification_appends_observed_test_evidence_and_blocks_writes(self):
        from unittest.mock import patch

        provider = SequenceProvider(
            '{"tool":"run_tests","arguments":{"command":"python -m unittest discover -s tests"}}',
            '{"tool":"write_file","arguments":{"path":"unsafe.py","content":"x"}}',
            '{"passed":true,"findings":[]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "run_tests", return_value="exit_code=0\nOK"):
                result = agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project")
            payload = json.loads(result)
            self.assertEqual(set(payload), {"passed", "findings", "tool_evidence"})
            self.assertTrue(any(
                item["tool"] == "run_tests" and "exit_code=0" in item["result"]
                for item in payload["tool_evidence"]
            ))
            self.assertFalse(Path(directory, "unsafe.py").exists())

    def test_final_verification_cannot_pass_without_observed_test_success(self):
        from unittest.mock import patch

        provider = SequenceProvider(
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"passed":true,"findings":[]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "list_files", return_value="README.md"):
                with self.assertRaisesRegex(AgentError, "observed successful test command output"):
                    agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project")

    def test_repair_prompt_mentioning_verification_can_still_edit_files(self):
        provider = SequenceProvider(
            '{"tool":"write_file","arguments":{"path":"repaired.txt","content":"fixed"}}',
            '{"final":"repair applied"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="repair")
            result = agent.run(
                "STREAMIOV_VERIFICATION_REPAIR: Repair the failure. "
                "Findings quote STREAMIOV_FINAL_VERIFICATION: inspect the project"
            )
            self.assertIn("repair applied", result)
            self.assertEqual(Path(directory, "repaired.txt").read_text(encoding="utf-8"), "fixed")

    def test_final_verification_can_use_observed_game_checks_evidence(self):
        from unittest.mock import patch

        provider = SequenceProvider(
            '{"tool":"run_game_checks","arguments":{}}',
            '{"passed":true,"findings":[]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "run_game_checks", return_value="exit_code=0\naudit ok") as checks:
                result = agent.run("STREAMIOV_FINAL_VERIFICATION: verify game work")
            checks.assert_called_once_with()
            payload = json.loads(result)
            self.assertIs(payload["passed"], True)
            self.assertTrue(any(
                item["tool"] == "run_game_checks" and "exit_code=0" in item["result"]
                for item in payload["tool_evidence"]
            ))

    def test_ai_games_agent_can_use_game_checks_outside_verification(self):
        from unittest.mock import patch

        provider = SequenceProvider(
            '{"tool":"run_game_checks","arguments":{}}',
            '{"final":"game checks observed"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="ai_games_agent")
            with patch.object(agent.tools, "run_game_checks", return_value="exit_code=0\naudit ok") as checks:
                result = agent.run("Inspect the game package")
            checks.assert_called_once_with()
            self.assertIn("game checks observed", result)

    def test_testing_role_outside_verification_cannot_run_game_checks(self):
        from unittest.mock import patch

        provider = SequenceProvider(
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"tool":"run_game_checks","arguments":{}}',
            '{"final":"inspection complete"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "list_files", return_value="README.md"), \
                 patch.object(agent.tools, "run_game_checks", return_value="exit_code=0") as checks:
                agent.run("Inspect the project")
            checks.assert_not_called()
            tool_output = "\n".join(
                message["content"]
                for call in provider.messages
                for message in call
                if message["role"] == "user"
            )
            self.assertIn("run_game_checks tool is restricted", tool_output)

    def test_verification_rejects_model_supplied_tool_evidence(self):
        from unittest.mock import patch

        provider = SequenceProvider(
            '{"tool":"run_tests","arguments":{"command":"python -m unittest discover -s tests"}}',
            '{"passed":true,"findings":[],'
            '"tool_evidence":[{"tool":"write_file","result":"exit_code=0"}]}',
            '{"passed":true,"findings":[]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "run_tests", return_value="exit_code=0\nOK"):
                result = agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project")
            payload = json.loads(result)
            self.assertEqual([item["tool"] for item in payload["tool_evidence"]], ["run_tests"])
            self.assertIn("exit_code=0", payload["tool_evidence"][0]["result"])
            correction = next(
                message["content"]
                for call in provider.messages
                for message in call
                if "FORMAT CORRECTION:" in message["content"]
            )
            self.assertIn("exactly the keys 'passed' and 'findings'", correction)


    def test_final_verification_report_without_tool_runs_observed_baseline_test(self):
        from unittest.mock import patch

        report = '{"passed":true,"findings":[]}'
        provider = SequenceProvider(report, report)
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "run_tests", return_value="exit_code=0\nOK") as tests:
                result = agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project")
            tests.assert_called_once_with("python -m unittest discover -s tests")
            payload = json.loads(result)
            self.assertIs(payload["passed"], True)
            self.assertTrue(any(
                item["tool"] == "run_tests" and "exit_code=0" in item["result"]
                for item in payload["tool_evidence"]
            ))

    def test_final_verification_baseline_failure_cannot_be_reported_as_passed(self):
        from unittest.mock import patch

        report = '{"passed":true,"findings":[]}'
        provider = SequenceProvider(report, report)
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "run_tests", return_value="exit_code=1\nFAILED"):
                with self.assertRaisesRegex(AgentError, "observed successful test command output"):
                    agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project")

    def test_final_verification_rejects_failed_exit_code_with_success_substring(self):
        from unittest.mock import patch

        provider = SequenceProvider(
            '{"tool":"run_tests","arguments":{"command":"python -m unittest discover -s tests"}}',
            '{"passed":true,"findings":[]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            with patch.object(agent.tools, "run_tests", return_value="exit_code=1\nFAILED; expected exit_code=0"):
                with self.assertRaisesRegex(AgentError, "observed successful test command output"):
                    agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project")

    def test_retry_diagnostic_is_persisted_once_across_checkpoint_resume(self):
        task = "Verify the project"
        diagnostic = (
            task
            + "\n\nPREVIOUS ATTEMPT FAILURE (untrusted diagnostic context):\n"
            + "previous verifier returned a report without observed tool output"
        )
        provider = SequenceProvider(
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"final":"Inspected and verified."}',
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory, "checkpoints.sqlite3")
            agent = DevelopmentAgent(provider, directory, specialist="research", checkpoint_db=database)
            agent.run(diagnostic, checkpoint_id="retry-diagnostic")
            resumed = DevelopmentAgent(
                SequenceProvider(), directory, specialist="research", checkpoint_db=database
            )
            self.assertEqual(
                resumed.run(diagnostic, checkpoint_id="retry-diagnostic"),
                "Inspected and verified.",
            )
            messages = AgentCheckpointStore(database).load(
                "retry-diagnostic", diagnostic, "research"
            )["messages"]
            notices = [
                message["content"] for message in messages
                if "RESUMED RETRY DIAGNOSTIC" in message["content"]
            ]
            self.assertEqual(len(notices), 1)
            self.assertIn("without observed tool output", notices[0])

    def test_unknown_tool_correction_names_the_invented_tool_and_real_alternatives(self):
        invented = json.dumps({
            "tool": "create_module",
            "arguments": {"module_name": "AI Chief", "module_path": "ai/modules/ai-chief.py"},
        })
        with self.assertRaisesRegex(AgentError, "create_module.*write_file"):
            _validate_tool_action(json.loads(invented))
        provider = SequenceProvider(
            invented,
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"final":"no invented tool was executed"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            result = agent.run("Inspect the workspace without inventing tools.")
            self.assertIn("no invented tool was executed", result)
            self.assertFalse(Path(directory, "ai", "modules", "ai-chief.py").exists())
        correction = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        for expected in ("create_module", "list_files", "write_file", "replace_text", "run_tests"):
            with self.subTest(expected=expected):
                self.assertIn(expected, correction)
        self.assertIn("Never invent tools", correction)

    def test_allowlisted_legacy_action_key_is_executed_without_a_correction_round(self):
        provider = SequenceProvider(
            '{"action":"list_files","arguments":{"path":"."}}',
            '{"final":"legacy action key recovered"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertIn("legacy action key recovered", agent.run("Use the documented tool key."))
        self.assertEqual(provider.calls, 2)
        self.assertFalse(any(
            "FORMAT CORRECTION:" in message["content"]
            for call in provider.messages
            for message in call
        ))

    def test_unknown_action_key_is_not_canonicalized_and_is_corrected(self):
        provider = SequenceProvider(
            '{"action":"create_module","arguments":{"path":"ai/file.py"}}',
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"final":"corrected the action key"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertIn("corrected the action key", agent.run("Use the documented tool key."))
        correction = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        self.assertIn("never 'action'", correction)
        self.assertIn("'tool' and 'arguments'", correction)
        self.assertIn("['action', 'arguments']", correction)
        self.assertIn("create_module", correction)

    def test_mixed_final_and_tool_correction_states_the_exclusive_final_rule(self):
        provider = SequenceProvider(
            '{"tool":"run_game_checks","arguments":{},"final":"No test passed"}',
            '{"tool":"list_files","arguments":{"path":"."}}',
            '{"final":"mixed response rejected"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertIn("mixed response rejected", agent.run("Do not mix final and tool fields."))
        correction = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        self.assertIn("Never mix a tool with a final field", correction)
        self.assertIn("only object and contain only a string 'final' field", correction)

    def test_final_verification_final_object_is_corrected_with_report_schema(self):
        provider = SequenceProvider(
            '{"final":"I verified everything"}',
            '{"passed":false,"findings":["No tests observed."]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            payload = json.loads(agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project"))
        self.assertIs(payload["passed"], False)
        self.assertEqual(provider.calls, 2)
        correction = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        self.assertIn("'passed'", correction)
        self.assertIn("'findings'", correction)
        self.assertIn("Do not use 'verdict', 'evidence'", correction)
        self.assertIn("Do not use a 'final' field", correction)
        self.assertIn("passed=true with non-empty findings is invalid", correction)

    def test_final_verification_invalid_report_schema_is_corrected(self):
        provider = SequenceProvider(
            '{"passed":false,"findings":42}',
            '{"passed":false,"findings":["No tests observed."]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="testing")
            payload = json.loads(agent.run("STREAMIOV_FINAL_VERIFICATION: inspect the project"))
        self.assertIs(payload["passed"], False)
        correction = next(
            message["content"]
            for call in provider.messages
            for message in call
            if "FORMAT CORRECTION:" in message["content"]
        )
        self.assertIn("non-empty strings", correction)
        self.assertIn("findings", correction)


class VerificationReportContractTests(unittest.TestCase):
    def test_pass_requires_empty_findings(self):
        validate_verification_report({"passed": True, "findings": []})
        with self.assertRaises(VerificationReportError):
            validate_verification_report({"passed": True, "findings": ["No tests observed."]})

    def test_fail_requires_concrete_findings(self):
        with self.assertRaises(VerificationReportError):
            validate_verification_report({"passed": False, "findings": []})
        validate_verification_report({
            "passed": False,
            "findings": [
                "Autonomer Chief-Lauf nicht nachgewiesen",
                "Mission nicht vollständig abgeschlossen",
            ],
        })

    def test_missing_or_invalid_fields_fail(self):
        invalid_reports = (
            {"passed": True},
            {"findings": []},
            {"passed": "true", "findings": []},
            {"verdict": "passed", "evidence": ["observed"], "findings": []},
            {"passed": True, "findings": [], "tool_evidence": []},
        )
        for payload in invalid_reports:
            with self.subTest(payload=payload), self.assertRaises(VerificationReportError):
                validate_verification_report(payload)

    def test_vague_or_non_string_findings_are_rejected(self):
        for finding in ("no errors detected", "ok", "looks good", 42, "x"):
            with self.subTest(finding=finding), self.assertRaises(VerificationReportError):
                validate_verification_report({"passed": False, "findings": [finding]})


if __name__ == "__main__":
    unittest.main()
