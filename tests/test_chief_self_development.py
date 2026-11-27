"""Owner-opted-in, narrowly scoped Chief self-development permissions."""
from pathlib import Path
import tempfile
import unittest

from ai.runtime.project_tools import ProjectTools, ToolError


CORE_FILES = (
    "ai/__main__.py",
    "ai/core/agent.py",
    "ai/runtime/continuous_engine.py",
    "ai/runtime/project_tools.py",
)


class ChiefSelfDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in CORE_FILES:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_core_files_remain_protected_by_default(self):
        tools = ProjectTools(self.root, writable_prefixes=("ai/",))
        for relative in CORE_FILES:
            with self.subTest(path=relative):
                with self.assertRaises(ToolError):
                    tools.replace_text(relative, "before", "after")

    def test_owner_opted_in_mission_can_edit_only_chief_core_files(self):
        tools = ProjectTools(
            self.root,
            writable_prefixes=("ai/",),
            allow_self_modification=True,
        )
        for relative in CORE_FILES:
            with self.subTest(path=relative):
                result = tools.replace_text(relative, "before", "after")
                self.assertIn("one exact match replaced", result)
                self.assertEqual((self.root / relative).read_text(encoding="utf-8"), "after")

    def test_full_project_development_unlocks_project_code_and_providers(self):
        tools = ProjectTools(
            self.root,
            writable_prefixes=("ai/",),
            full_project_development=True,
        )
        for relative in ("src/app.js", "studio/main.js", "ai/providers/local_http.py", "ai/__main__.py"):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before", encoding="utf-8")
            with self.subTest(path=relative):
                result = tools.replace_text(relative, "before", "after")
                self.assertIn("one exact match replaced", result)

    def test_full_project_development_keeps_secrets_workflows_deploy_and_runner_controls_locked(self):
        tools = ProjectTools(self.root, full_project_development=True)
        protected = (
            ".github/workflows/checks.yml",
            "scripts/autonomous/run_issue.py",
            "scripts/ai/run-chief-mission.sh",
            "infrastructure/cloudflare/streamiov-ai-worker/src/index.ts",
            "host/auth.py",
            "scripts/release-signing.mjs",
            "scripts/build-ffmpeg-source-bundle.py",
            "Dockerfile",
            "wrangler.toml",
            "config/client_secret.json",
            "keys/signing.pem",
        )
        for relative in protected:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("before", encoding="utf-8")
            with self.subTest(path=relative):
                with self.assertRaises(ToolError):
                    tools.replace_text(relative, "before", "after")

    def test_self_development_does_not_unlock_providers_or_workflows(self):
        tools = ProjectTools(
            self.root,
            writable_prefixes=("*",),
            allow_self_modification=True,
        )
        provider = self.root / "ai/providers/local_http.py"
        provider.parent.mkdir(parents=True, exist_ok=True)
        provider.write_text("before", encoding="utf-8")
        workflow = self.root / ".github/workflows/checks.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("before", encoding="utf-8")

        with self.assertRaises(ToolError):
            tools.replace_text("ai/providers/local_http.py", "before", "after")
        with self.assertRaises(ToolError):
            tools.replace_text(".github/workflows/checks.yml", "before", "after")


if __name__ == "__main__":
    unittest.main()
