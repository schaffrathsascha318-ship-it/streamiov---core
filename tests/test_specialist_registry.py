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

    def test_every_specialist_has_project_wide_scope_and_shared_permission_boundaries(self):
        from ai.specialists import SPECIALISTS
        from ai.specialists.registry import PROJECT_WRITE_SCOPE
        from ai.__main__ import build_parser

        names = specialist_names()
        self.assertEqual(len(names), 11)
        self.assertEqual(set(names), set(SPECIALISTS))
        parser_names = set(build_parser()._option_string_actions["--specialist"].choices)
        self.assertEqual(parser_names, set(names))
        self.assertEqual(PROJECT_WRITE_SCOPE, ("*",))
        for name in names:
            definition = SPECIALISTS[name]
            self.assertTrue(definition.title.strip())
            self.assertTrue(definition.mission.strip())
            self.assertEqual(definition.writable_prefixes, PROJECT_WRITE_SCOPE, name)

    def test_specialist_prompt_contains_mission_and_write_scope(self):
        prompt = build_specialist_system_prompt("game", "Base instructions")
        self.assertIn("Game Developer", prompt)
        self.assertIn("original games", prompt)
        self.assertIn("games/", prompt)
        self.assertIn("runtime enforces project-wide access", prompt)

    def test_specialists_can_write_across_project_but_protected_controls_stay_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = ProjectTools(root, writable_prefixes=get_specialist("testing").writable_prefixes)
            tools.write_file("tests/new_test.py", "# test\n")
            tools.write_file("ai/new_runtime_test.py", "# cross-module test\n")
            tools.write_file("core/new_contract.py", "# shared contract\n")
            tools.write_file("dist/streamiov-studio-app/new_module.js", "// studio module\n")
            for path in (
                ".github/workflows/new-workflow.yml",
                ".github/actions/new-action/action.yml",
                "scripts/autonomous/new-runner.py",
                "ai/runtime/project_tools.py",
                "ai/specialists/registry.py",
                "services/oauth/new_provider.py",
            ):
                with self.subTest(path=path), self.assertRaises(ToolError):
                    tools.write_file(path, "# protected\n")

    def test_domain_specialists_can_reach_shared_modules_and_host_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_tools = ProjectTools(root, writable_prefixes=get_specialist("code").writable_prefixes)
            integration_tools = ProjectTools(root, writable_prefixes=get_specialist("integration").writable_prefixes)
            server_tools = ProjectTools(root, writable_prefixes=get_specialist("server").writable_prefixes)

            code_tools.write_file("modules/music/new_feature.py", "# module work\n")
            integration_tools.write_file("host/new_adapter.py", "# host integration\n")
            integration_tools.write_file("services/new_service.py", "# service integration\n")
            server_tools.write_file("host/new_healthcheck.py", "# server health check\n")

            with self.assertRaises(ToolError):
                integration_tools.write_file("services/oauth/new_provider.py", "# protected OAuth path\n")

    def test_specialist_prompt_states_protected_paths_remain_blocked(self):
        prompt = build_specialist_system_prompt("integration", "Base instructions")
        self.assertIn("Protected OAuth, credential, secret, workflow, runner-permission, and access-control paths remain inaccessible", prompt)

    def test_development_agent_uses_role_prompt_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider()
            agent = DevelopmentAgent(provider, tmp, specialist="testing")
            self.assertEqual(agent.run("Inspect tests"), "role prompt received")
            self.assertIn("Quality Engineer", provider.system)
            self.assertIn("project files across all modules", provider.system)
            agent.tools.write_file("ai/cross_module_test.py", "allowed")
            with self.assertRaises(ToolError):
                agent.tools.write_file(".github/workflows/unsafe.yml", "blocked")


if __name__ == "__main__":
    unittest.main()
