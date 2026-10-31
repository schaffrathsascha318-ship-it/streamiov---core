import json
import unittest

from ai.core.agent import _parse_action


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


if __name__ == "__main__":
    unittest.main()
