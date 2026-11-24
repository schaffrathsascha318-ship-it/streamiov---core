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
from ai.providers.base import ModelReply


class SequenceProvider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.messages = []

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        self.calls += 1
        self.messages.append(messages)
        if not self.responses:
            raise AssertionError("Unexpected extra model request.")
        return ModelReply(self.responses.pop(0), "test", "fixture")


class SpecialistActionProtocolTests(unittest.TestCase):

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
            recovery = provider.messages[0][-1]["content"]
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
        self.assertEqual(fitted, [original, repeated])

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
            self.assertIn("Verified tool evidence: write_file", result)
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
        correction = provider.messages[1][-1]["content"]
        self.assertIn("allowed keys are ['content', 'path']", correction)
        self.assertIn("unexpected keys are ['extra']", correction)

    def test_read_file_offset_and_length_are_rejected_with_actionable_schema_feedback(self):
        invalid = json.dumps({
            "tool": "read_file",
            "arguments": {"path": "README.md", "offset": "400", "length": "150"},
        })
        provider = SequenceProvider(invalid, '{"tool":"list_files","arguments":{"path":"."}}', '{"final":"corrected"}')
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertIn("corrected", agent.run("Read the README safely."))
        diagnostic = provider.messages[1][-1]["content"]
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
            agent = DevelopmentAgent(provider, directory, specialist="research")
            result = agent.run("Inspect the project.")
            self.assertIn("Verified tool evidence: list_files", result)

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
        self.assertIn("unexpected keys are ['unexpected']", provider.messages[1][-1]["content"])

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
        self.assertEqual(provider.calls, 2)


if __name__ == "__main__":
    unittest.main()
