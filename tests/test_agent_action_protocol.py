"""Regression tests for the specialist model-to-tool action protocol."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.core.agent import (
    AgentError,
    DevelopmentAgent,
    _parse_actions,
    _validate_tool_action,
)
from ai.providers.base import ModelReply


class SequenceProvider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        self.calls += 1
        if not self.responses:
            raise AssertionError("Unexpected extra model request.")
        return ModelReply(self.responses.pop(0), "test", "fixture")


class SpecialistActionProtocolTests(unittest.TestCase):
    def test_parses_single_object_array_and_fenced_json(self):
        action = {"tool": "list_files", "arguments": {"path": "."}}
        self.assertEqual(_parse_actions('{"tool":"list_files","arguments":{"path":"."}}'), [action])
        self.assertEqual(_parse_actions('[{"tool":"list_files","arguments":{"path":"."}}]'), [action])
        fenced = "```json\n" + '{"tool":"list_files","arguments":{"path":"."}}' + "\n```"
        self.assertEqual(_parse_actions(fenced), [action])

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
            self.assertEqual(result, "created")
            self.assertEqual(Path(directory, "ai", "created.py").read_text(encoding="utf-8"), "safe")
        self.assertEqual(provider.calls, 2)

    def test_schema_invalid_action_is_corrected_without_execution(self):
        provider = SequenceProvider(
            '{"tool":"write_file","arguments":{"path":"blocked.txt","content":"bad","extra":"no"}}',
            '{"final":"no action executed"}',
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            self.assertEqual(agent.run("Do not create blocked.txt."), "no action executed")
            self.assertFalse(Path(directory, "blocked.txt").exists())
        self.assertEqual(provider.calls, 2)

    def test_malformed_replies_have_one_bounded_correction_per_run(self):
        provider = SequenceProvider("not json", "still not json")
        with tempfile.TemporaryDirectory() as directory:
            agent = DevelopmentAgent(provider, directory, specialist="code")
            with self.assertRaisesRegex(AgentError, "bounded corrections"):
                agent.run("Perform a harmless task.")
        self.assertEqual(provider.calls, 2)


if __name__ == "__main__":
    unittest.main()
