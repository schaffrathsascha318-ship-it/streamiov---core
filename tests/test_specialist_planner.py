import unittest

from ai.core.planner import PlannerError, SpecialistPlanner


class FakeProvider:
    def __init__(self, content):
        self.content = content
        self.system = None
        self.messages = None

    def generate(self, *, system, messages):
        self.system = system
        self.messages = messages
        class Reply:
            def __init__(self, content):
                self.content = content
        return Reply(self.content)


class SpecialistPlannerTests(unittest.TestCase):
    def test_plans_tasks_and_rewrites_ids_to_a_unique_plan_namespace(self):
        provider = FakeProvider('{"tasks":['
            '{"id":"core","specialist":"core","prompt":"Define shared event contracts","depends_on":[]},'
            '{"id":"studio","specialist":"studio","prompt":"Integrate event contracts","depends_on":["core"]},'
            '{"id":"game","specialist":"game","prompt":"Build an independent original game","depends_on":[]}'
            ']}')
        tasks = SpecialistPlanner(provider).plan("Build new features", plan_id="plan-123")
        self.assertEqual([task.task_id for task in tasks], ["plan-123-core", "plan-123-studio", "plan-123-game"])
        self.assertEqual(tasks[1].depends_on, ("plan-123-core",))
        self.assertIn("directed acyclic graph", provider.system)
        self.assertEqual(provider.messages[0]["content"], "Build new features")

    def test_rejects_invalid_json_and_extra_top_level_fields(self):
        for response in ("not json", '{"tasks":[],"comment":"unsafe"}'):
            with self.subTest(response=response), self.assertRaises(PlannerError):
                SpecialistPlanner(FakeProvider(response)).plan("Plan this")

    def test_rejects_duplicate_ids_unknown_roles_and_unknown_dependencies(self):
        responses = [
            '{"tasks":[{"id":"a","specialist":"code","prompt":"A","depends_on":[]},{"id":"a","specialist":"game","prompt":"B","depends_on":[]}]}',
            '{"tasks":[{"id":"a","specialist":"root","prompt":"A","depends_on":[]}]}',
            '{"tasks":[{"id":"a","specialist":"code","prompt":"A","depends_on":["missing"]}]}',
        ]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(PlannerError):
                SpecialistPlanner(FakeProvider(response)).plan("Plan this")

    def test_rejects_dependency_cycles_before_returning_plan(self):
        response = '{"tasks":['
        response += '{"id":"a","specialist":"core","prompt":"A","depends_on":["b"]},'
        response += '{"id":"b","specialist":"code","prompt":"B","depends_on":["a"]}]}'
        with self.assertRaises(PlannerError):
            SpecialistPlanner(FakeProvider(response)).plan("Plan this")

    def test_enforces_task_and_prompt_limits(self):
        too_many = '{"tasks":[' + ",".join(
            '{"id":"t%d","specialist":"code","prompt":"task","depends_on":[]}' % index
            for index in range(13)
        ) + ']}'
        with self.assertRaises(PlannerError):
            SpecialistPlanner(FakeProvider(too_many)).plan("Plan this")
        with self.assertRaises(PlannerError):
            SpecialistPlanner(FakeProvider('{"tasks":[{"id":"a","specialist":"code","prompt":"","depends_on":[]}]}')).plan("Plan this")
        with self.assertRaises(PlannerError):
            SpecialistPlanner(FakeProvider('{"tasks":[{"id":"a","specialist":"code","prompt":"A","depends_on":[]}]}')).plan("Plan this", plan_id="../unsafe")


if __name__ == "__main__":
    unittest.main()
