import unittest

from ai.core.orchestrator import SpecialistTask, TaskOrchestrator, TaskPlanError


class FakeAgent:
    def __init__(self, specialist, calls, failures=()):
        self.specialist = specialist
        self.calls = calls
        self.failures = set(failures)

    def run(self, prompt):
        self.calls.append((self.specialist, prompt))
        if prompt in self.failures:
            raise RuntimeError("simulated specialist failure")
        return f"{self.specialist}: {prompt}"


class OrchestratorTests(unittest.TestCase):
    def test_runs_tasks_in_dependency_order_and_preserves_independent_work(self):
        calls = []
        orchestrator = TaskOrchestrator(lambda role: FakeAgent(role, calls))
        results = orchestrator.run([
            SpecialistTask("studio", "studio", "build studio module", ("core",)),
            SpecialistTask("core", "core", "define shared contract"),
            SpecialistTask("game", "game", "build independent game"),
        ])
        self.assertEqual([result.task_id for result in results], ["core", "game", "studio"])
        self.assertTrue(all(result.status == "succeeded" for result in results))
        self.assertEqual(calls[0], ("core", "define shared contract"))
        self.assertIn(("game", "build independent game"), calls)

    def test_failed_dependency_skips_only_its_dependants(self):
        calls = []
        orchestrator = TaskOrchestrator(lambda role: FakeAgent(role, calls, {"fail core"}))
        results = orchestrator.run([
            SpecialistTask("core", "core", "fail core"),
            SpecialistTask("studio", "studio", "dependent work", ("core",)),
            SpecialistTask("game", "game", "independent work"),
        ])
        by_id = {result.task_id: result for result in results}
        self.assertEqual(by_id["core"].status, "failed")
        self.assertEqual(by_id["studio"].status, "skipped")
        self.assertEqual(by_id["game"].status, "succeeded")

    def test_invalid_cycle_is_rejected_before_any_agent_runs(self):
        calls = []
        orchestrator = TaskOrchestrator(lambda role: FakeAgent(role, calls))
        with self.assertRaises(TaskPlanError):
            orchestrator.run([
                SpecialistTask("a", "core", "A", ("b",)),
                SpecialistTask("b", "code", "B", ("a",)),
            ])
        self.assertEqual(calls, [])

    def test_unknown_dependency_and_role_are_rejected(self):
        orchestrator = TaskOrchestrator(lambda role: FakeAgent(role, []))
        with self.assertRaises(TaskPlanError):
            orchestrator.run([SpecialistTask("a", "core", "A", ("missing",))])
        with self.assertRaises(ValueError):
            orchestrator.run([SpecialistTask("a", "root", "A")])

    def test_task_count_and_empty_plan_are_bounded(self):
        orchestrator = TaskOrchestrator(lambda role: FakeAgent(role, []), max_tasks=1)
        with self.assertRaises(TaskPlanError):
            orchestrator.run([])
        with self.assertRaises(TaskPlanError):
            orchestrator.run([SpecialistTask("a", "core", "A"), SpecialistTask("b", "game", "B")])


if __name__ == "__main__":
    unittest.main()
