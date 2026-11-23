import contextlib
import io
import json
import unittest

from scripts.autonomous.run_issue import ObservedProvider


class FakeReply:
    content = "ok"


class FakeProvider:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def generate(self, *, system, messages):
        self.calls.append((system, messages))
        if self.error:
            raise self.error
        return FakeReply()


class ObservedProviderTests(unittest.TestCase):
    def test_emits_start_and_completion_without_logging_prompt_content(self):
        provider = FakeProvider()
        observed = ObservedProvider(provider)
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            reply = observed.generate(
                system="private system prompt",
                messages=[{"role": "user", "content": "private user prompt"}],
            )

        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(reply.content, "ok")
        self.assertEqual([event["event"] for event in events], [
            "model_request_started", "model_request_completed"
        ])
        self.assertEqual(events[0]["request_id"], events[1]["request_id"])
        self.assertEqual(events[0]["message_count"], 1)
        self.assertNotIn("private", output.getvalue())

    def test_emits_sanitized_failure_class_and_reraises(self):
        provider = FakeProvider(RuntimeError("private diagnostic"))
        observed = ObservedProvider(provider)
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, "private diagnostic"):
                observed.generate(system="system", messages=[])

        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(events[-1]["event"], "model_request_failed")
        self.assertEqual(events[-1]["error_class"], "RuntimeError")
        self.assertNotIn("private diagnostic", output.getvalue())

    def test_passes_through_other_provider_attributes(self):
        provider = FakeProvider()
        observed = ObservedProvider(provider)
        self.assertIs(observed.calls if hasattr(observed, "calls") else observed._provider.calls, provider.calls)


if __name__ == "__main__":
    unittest.main()
