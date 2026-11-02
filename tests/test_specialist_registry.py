import tempfile
import unittest
from pathlib import Path

from ai.core.agent import DevelopmentAgent
from ai.runtime.project_tools import ProjectTools, ToolError
from ai.specialists import get_specialist, specialist_names
from ai.specialists.registry import SPECIALISTS, build_specialist_system_prompt


EXPECTED_SPECIALISTS = {
    "core", "code", "game", "design", "gifts", "testing",
    "repair", "integration", "studio", "server", "general",
}


class FakeProvider:
    def __init__(self):
        self.system = None

    def generate(self, *, system, messages):
        self.system = system

        class Reply:
            content = '{"final":"role prompt received"}'

        return Reply()


class SpecialistRegistryTests(unittest.TestCase):
    def test_registry_contains_exactly_the_eleven_existing_roles(self):
        self.assertEqual(set(specialist_names()), EXPECTED_SPECIALISTS)
        self.assertEqual(set(SPECIALISTS), EXPECTED_SPECIALISTS)

    def test_role_ids_are_unique_and_match_the_registry_keys(self):
        keys = list(SPECIALISTS)
        self.assertEqual(len(keys), len(set(keys)))
        for key, definition in SPECIALISTS.items():
            with self.subTest(role=key):
                self.assertEqual(definition.key, key)

    def test_every_role_has_valid_nonempty_relative_write_prefixes(self):
        for key, definition in SPECIALISTS.items():
            with self.subTest(role=key):
                self.assertTrue(definition.writable_prefixes)
                self.assertEqual(len(definition.writable_prefixes), len(set(definition.writable_prefixes)))
                for prefix in definition.writable_prefixes:
                    self.assertIsInstance(prefix, str)
                    self.assertTrue(prefix.endswith("/"))
                    self.assertFalse(prefix.startswith(("/", "\\\\")))
                    self.assertNotIn("..", prefix.split("/"))
                    self.assertNotIn("\\\\", prefix)

    def test_every_role_prompt_contains_its_mission_and_write_boundaries(self):
        for key, definition in SPECIALISTS.items():
            with self.subTest(role=key):
                prompt = build_specialist_system_prompt(key, "Base instructions")
                self.assertIn(f"{definition.title} ({key})", prompt)
                self.assertIn(f"MISSION: {definition.mission}", prompt)
                self.assertIn("WRITE SCOPE:", prompt)
                for prefix in definition.writable_prefixes:
                    self.assertIn(prefix, prompt)
                self.assertIn("runtime enforces this scope independently", prompt)

    def test_unknown_specialist_is_rejected(self):
        with self.assertRaises(ValueError):
            get_specialist("superuser")

    def test_project_tools_enforce_role_specific_write_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = ProjectTools(root, writable_prefixes=get_specialist("testing").writable_prefixes)
            tools.write_file("tests/new_test.py", "# test\\n")
            with self.assertRaises(ToolError):
                tools.write_file("ai/not_allowed.py", "# outside role\\n")

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
