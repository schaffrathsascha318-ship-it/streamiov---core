import tempfile
import unittest

from ai.core.agent import AgentError
from ai.core.coordinator import (
    CoordinatorError,
    CoordinatorStep,
    DevelopmentCoordinator,
)


class FakeProvider:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        if not self.outputs:
            raise AssertionError("No prepared model response remains.")

        class Reply:
            def __init__(self, content):
                self.content = content

        return Reply(self.outputs.pop(0))


class CoordinatorTests(unittest.TestCase):
    def test_runs_specialists_in_sequence(self):
        provider = FakeProvider([
            '{"final":"Studio reviewed."}',
            '{"final":"Quality reviewed."}',
        ])

        with tempfile.TemporaryDirectory() as root:
            coordinator = DevelopmentCoordinator(provider, root)
            result = coordinator.run([
                CoordinatorStep("studio", "Review the Studio."),
                CoordinatorStep("quality", "Review quality."),
            ])

        self.assertEqual(
            [item.role for item in result],
            ["studio", "quality"],
        )
        self.assertEqual(provider.calls, 2)

    def test_stops_when_a_specialist_fails(self):
        provider = FakeProvider([
            '{"final":"First completed."}',
            "not JSON",
            "still not JSON",
            '{"final":"Must not run."}',
        ])

        with tempfile.TemporaryDirectory() as root:
            coordinator = DevelopmentCoordinator(provider, root)

            with self.assertRaises(CoordinatorError) as caught:
                coordinator.run([
                    CoordinatorStep("studio", "First task."),
                    CoordinatorStep("quality", "Second task."),
                    CoordinatorStep("design", "Third task."),
                ])

        error = caught.exception
        self.assertEqual(error.failed_role, "quality")
        self.assertEqual(
            [item.role for item in error.completed],
            ["studio"],
        )
        self.assertIsInstance(error.cause, AgentError)
        self.assertEqual(provider.calls, 3)
        self.assertEqual(len(provider.outputs), 1)

    def test_validates_entire_plan_before_model_calls(self):
        provider = FakeProvider([])

        with tempfile.TemporaryDirectory() as root:
            coordinator = DevelopmentCoordinator(provider, root)

            with self.assertRaises(ValueError):
                coordinator.run([
                    CoordinatorStep("studio", "First."),
                    CoordinatorStep("studio", "Duplicate."),
                ])

        self.assertEqual(provider.calls, 0)

    def test_rejects_unknown_role(self):
        provider = FakeProvider([])

        with tempfile.TemporaryDirectory() as root:
            coordinator = DevelopmentCoordinator(provider, root)

            with self.assertRaises(ValueError):
                coordinator.run([
                    CoordinatorStep("unknown", "Do work."),
                ])

        self.assertEqual(provider.calls, 0)

    def test_rejects_empty_task(self):
        provider = FakeProvider([])

        with tempfile.TemporaryDirectory() as root:
            coordinator = DevelopmentCoordinator(provider, root)

            with self.assertRaises(ValueError):
                coordinator.run([
                    CoordinatorStep("studio", "  "),
                ])

        self.assertEqual(provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
