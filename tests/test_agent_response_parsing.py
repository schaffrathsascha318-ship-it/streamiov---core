import json
import unittest

from ai.core.agent import _parse_action, _parse_actions


class AgentResponseParsingTests(unittest.TestCase):
    def test_parses_plain_json(self):
        action = _parse_action('{"final":"ok"}')
        self.assertEqual(action, {"final": "ok"})

    def test_parses_markdown_json_fence(self):
        raw = '```json\n{"tool":"read_file","arguments":{"path":"ai/core/agent.py"}}\n```'
        action = _parse_action(raw)
        self.assertEqual(action["tool"], "read_file")
        self.assertEqual(action["arguments"]["path"], "ai/core/agent.py")

    def test_parses_unlabelled_markdown_fence(self):
        self.assertEqual(_parse_action('```\n{"final":"ok"}\n```'), {"final": "ok"})

    def test_rejects_prose_outside_json_fence(self):
        with self.assertRaises(json.JSONDecodeError):
            _parse_action('Here is the JSON:\n```json\n{"final":"ok"}\n```')

    def test_parses_multiple_adjacent_json_actions(self):
        raw = (
            '{"tool":"read_file","arguments":{"path":"ai/core/agent.py"}}'
            '{"tool":"read_file","arguments":{"path":"ai/runtime/project_tools.py"}}'
            '{"tool":"read_file","arguments":{"path":"tests/test_cloudflare_worker_provider.py"}}'
        )
        actions = _parse_actions(raw)
        self.assertEqual(len(actions), 3)
        self.assertEqual([item["arguments"]["path"] for item in actions], [
            "ai/core/agent.py",
            "ai/runtime/project_tools.py",
            "tests/test_cloudflare_worker_provider.py",
        ])

    def test_parses_multiple_actions_inside_json_fence(self):
        raw = '```json\n{"tool":"read_file","arguments":{"path":"a.py"}}\n{"tool":"read_file","arguments":{"path":"b.py"}}\n```'
        self.assertEqual(len(_parse_actions(raw)), 2)

    def test_rejects_prose_after_multiple_json_actions(self):
        raw = '{"tool":"read_file","arguments":{"path":"a.py"}} done'
        with self.assertRaises(json.JSONDecodeError):
            _parse_actions(raw)

    def test_single_action_helper_rejects_multiple_objects(self):
        with self.assertRaises(ValueError):
            _parse_action('{"final":"one"}{"final":"two"}')


if __name__ == "__main__":
    unittest.main()
