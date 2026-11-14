import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "autonomous-development.yml"


class AutonomousWorkflowGuardTests(unittest.TestCase):
    def test_change_and_deletion_detection_include_staged_changes(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("git diff HEAD --name-only", source)
        self.assertIn("git diff HEAD --diff-filter=D --name-only", source)
        self.assertNotIn("git diff --name-only;", source)

    def test_ci_independently_blocks_all_agent_control_plane_paths(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        required = (
            "ai/__main__.py",
            "ai/runtime/project_tools.py",
            "ai/security/*",
            ".github/*",
            "scripts/autonomous/*",
            "*oauth*",
            "*credential*",
            "*secret*",
        )
        for pattern in required:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, source)
        self.assertNotIn("ai/core/agent.py", source)
        self.assertNotIn("ai/runtime/continuous_engine.py", source)
        self.assertNotIn("ai/providers/*", source)

    def test_public_mission_artifacts_are_encrypted_before_upload(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions/upload-artifact@v4", source)
        self.assertIn("gh run download", source)
        self.assertIn("mission-state.enc", source)
        self.assertIn("mission-state-crypto.mjs encrypt", source)
        self.assertIn("mission-state-crypto.mjs decrypt", source)
        self.assertIn("aes-256-gcm", (ROOT / "scripts" / "autonomous" / "mission-state-crypto.mjs").read_text(encoding="utf-8"))
        self.assertIn("STREAMIOV_AI_WORKER_TOKEN", source)
        self.assertNotIn("path: ${{ runner.temp }}/streamiov-ai-missions/", source)
        self.assertNotIn("actions/cache/save@", source)
        self.assertNotIn("actions/cache/restore@", source)

    def test_ci_rejects_sensitive_files_and_symlink_changes(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        for pattern in ("*.pem", "*.key", "*.p12", "*.pfx", ".env*", ".ssh/*", "wrangler.jsonc", "wrangler.toml"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, source)
        self.assertIn('[[ -L "$path" ]]', source)
        self.assertIn("Autonomous deletion is not permitted", source)


if __name__ == "__main__":
    unittest.main()
