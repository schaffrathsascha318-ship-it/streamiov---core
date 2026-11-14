import tempfile
import unittest
from pathlib import Path

from ai.core.agent import DevelopmentAgent
from ai.runtime.project_tools import ProjectTools, ToolError
from ai.specialists import get_specialist, specialist_names
from ai.specialists.registry import build_specialist_system_prompt


class FakeProvider:
    def __init__(self):
        self.system = None

    def generate(self, *, system, messages):
        self.system = system
        class Reply:
            content = '{"final":"role prompt received"}'
        return Reply()


class SpecialistRegistryTests(unittest.TestCase):
    def test_all_required_specialist_roles_are_registered(self):
        expected = {"core", "code", "game", "design", "gifts", "testing", "repair", "integration", "studio", "server", "general"}
        self.assertTrue(expected.issubset(set(specialist_names())))

    def test_unknown_specialist_is_rejected(self):
        with self.assertRaises(ValueError):
            get_specialist("superuser")

    def test_every_specialist_has_a_unique_safe_write_scope(self):
        from ai.specialists import SPECIALISTS
        from ai.__main__ import build_parser

        names = specialist_names()
        self.assertEqual(len(names), 12)
        self.assertEqual(set(names), set(SPECIALISTS))
        parser_names = set(build_parser()._option_string_actions["--specialist"].choices)
        self.assertEqual(parser_names, set(names))
        for name in names:
            definition = SPECIALISTS[name]
            self.assertTrue(definition.title.strip())
            self.assertTrue(definition.mission.strip())
            self.assertTrue(definition.writable_prefixes)
            self.assertEqual(
                len(definition.writable_prefixes),
                len(set(definition.writable_prefixes)),
                f"{name} lists a duplicate scope",
            )
            for prefix in definition.writable_prefixes:
                self.assertFalse(prefix.startswith("/"), f"{name} has an absolute scope: {prefix}")
                self.assertNotIn("..", prefix, f"{name} escapes its scope: {prefix}")
                if prefix == "**":
                    self.assertEqual(name, "chief", "Only the Chief may have project-wide write scope")
                else:
                    self.assertTrue(prefix.endswith("/"), f"{name} scope must be a directory prefix: {prefix}")

    def test_specialist_prompt_contains_mission_and_write_scope(self):
        prompt = build_specialist_system_prompt("game", "Base instructions")
        self.assertIn("Game Developer", prompt)
        self.assertIn("original games", prompt)
        self.assertIn("games/", prompt)
        self.assertIn("runtime enforces this scope", prompt)

    def test_project_tools_enforce_role_specific_write_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = ProjectTools(root, writable_prefixes=get_specialist("testing").writable_prefixes)
            tools.write_file("tests/new_test.py", "# test\n")
            with self.assertRaises(ToolError):
                tools.write_file("ai/not_allowed.py", "# outside role\n")

    def test_development_agent_uses_role_prompt_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider()
            agent = DevelopmentAgent(provider, tmp, specialist="testing")
            self.assertEqual(agent.run("Inspect tests"), "role prompt received")
            self.assertIn("Quality Engineer", provider.system)
            self.assertIn("tests/", provider.system)
            with self.assertRaises(ToolError):
                agent.tools.write_file("ai/outside.py", "blocked")


if __name__ == "__main__":
    unittest.main()
