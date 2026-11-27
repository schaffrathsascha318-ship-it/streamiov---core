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
            '{"id":"t%d","specialist":"code","prompt":"distinct task %d","depends_on":[]}' % (index, index)
            for index in range(51)
        ) + ']}'
        with self.assertRaises(PlannerError):
            SpecialistPlanner(FakeProvider(too_many)).plan("Plan this")
        with self.assertRaises(PlannerError):
            SpecialistPlanner(FakeProvider('{"tasks":[{"id":"a","specialist":"code","prompt":"","depends_on":[]}]}')).plan("Plan this")
        with self.assertRaises(PlannerError):
            SpecialistPlanner(FakeProvider('{"tasks":[{"id":"a","specialist":"code","prompt":"A","depends_on":[]}]}')).plan("Plan this", plan_id="../unsafe")

    def test_accepts_multiple_independent_workers_sharing_one_specialist(self):
        provider = FakeProvider('{"tasks":['
            '{"id":"repo-audit","specialist":"code","prompt":"Audit repository boundaries","depends_on":[]},'
            '{"id":"test-repair","specialist":"code","prompt":"Repair failing tests","depends_on":["repo-audit"]}'
            ']}')
        tasks = SpecialistPlanner(provider).plan("Run two independent code workstreams", plan_id="shared")
        self.assertEqual([task.task_id for task in tasks], ["shared-repo-audit", "shared-test-repair"])
        self.assertEqual([task.specialist for task in tasks], ["code", "code"])
        self.assertEqual(tasks[1].depends_on, ("shared-repo-audit",))
        self.assertIn("Multiple independent workers may share", " ".join(provider.system.split()))

    def test_rejects_duplicate_assignment_to_the_same_specialist(self):
        response = '{"tasks":['
        response += '{"id":"a","specialist":"code","prompt":"same deliverable","depends_on":[]},'
        response += '{"id":"b","specialist":"code","prompt":"SAME DELIVERABLE","depends_on":[]}]}'
        with self.assertRaisesRegex(PlannerError, "duplicate assignment"):
            SpecialistPlanner(FakeProvider(response)).plan("Plan this")

    def test_planner_accepts_registered_ai_agents_and_publishes_the_full_role_list(self):
        from ai.specialists import specialist_names

        provider = FakeProvider('{"tasks":['
            '{"id":"security","specialist":"ai_security_agent","prompt":"Review permission boundaries","depends_on":[]},'
            '{"id":"release","specialist":"ai_release_agent","prompt":"Prepare release evidence","depends_on":["security"]}'
            ']}')
        tasks = SpecialistPlanner(provider).plan("Finish the Chief rollout", plan_id="registered")
        self.assertEqual(
            [task.specialist for task in tasks],
            ["ai_security_agent", "ai_release_agent"],
        )
        self.assertEqual(tasks[1].depends_on, ("registered-security",))
        for name in specialist_names():
            self.assertIn(name, provider.system)


if __name__ == "__main__":
    unittest.main()
