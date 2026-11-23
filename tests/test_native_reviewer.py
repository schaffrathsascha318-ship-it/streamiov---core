"""Tests for the provider-free Streamiov native reviewer."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai.review.independent_reviewer import (
    classify_changed_path,
    parse_name_status,
    review_repository,
    scan_added_lines,
)


class NativeReviewerPolicyTests(unittest.TestCase):
    def test_provider_and_control_plane_changes_are_flagged(self):
        for path in (
            ".github/workflows/release.yml",
            "scripts/autonomous/run_issue.py",
            "ai/providers/cloudflare_worker.py",
            "ai/security/permissions.py",
            "ai/review/independent_reviewer.py",
            "ai/runtime/continuous_engine.py",
            "ai/runtime/project_tools.py",
            "wrangler.toml",
        ):
            with self.subTest(path=path):
                finding = classify_changed_path(path)
                self.assertIsNotNone(finding)
                self.assertEqual(finding.severity, "high")

    def test_unapproved_ai_provider_imports_and_endpoints_are_high(self):
        diff = (
            "diff --git a/ai/client.py b/ai/client.py\n"
            "--- a/ai/client.py\n+++ b/ai/client.py\n"
            "@@ -1,0 +1,2 @@\n"
            "+import anthropic\n"
            "+BASE_URL = 'https://api.openai.com/v1'\n"
        )
        findings = scan_added_lines(diff)
        self.assertEqual({item.code for item in findings}, {
            "unapproved-ai-provider-import", "unapproved-ai-provider-endpoint",
        })
        self.assertTrue(all(item.severity == "high" for item in findings))

    def test_only_tiktok_and_twitch_live_adapter_paths_are_allowed(self):
        for path in (
            "platforms/youtube/client.ts", "adapters/obs/bridge.js",
            "integrations/kick/adapter.py", "integrations/facebook/adapter.py",
        ):
            with self.subTest(path=path):
                finding = classify_changed_path(path)
                self.assertIsNotNone(finding)
                self.assertEqual(finding.code, "unsupported-platform-adapter")
        self.assertIsNone(classify_changed_path("integrations/tiktok/live_adapter.py"))
        self.assertIsNone(classify_changed_path("integrations/twitch/live_adapter.py"))
    def test_private_credentials_and_environment_files_are_critical(self):
        for path in ("keys/signing.pem", "config/client.key", ".env.production", ".env"):
            with self.subTest(path=path):
                finding = classify_changed_path(path)
                self.assertIsNotNone(finding)
                self.assertEqual(finding.severity, "critical")

    def test_name_status_parses_add_modify_delete_and_rename(self):
        parsed = parse_name_status(
            "A\tai/new.py\nM\tREADME.md\nD\told.txt\nR100\told.py\tnew.py\n"
        )
        self.assertEqual(parsed, ["README.md", "ai/new.py", "new.py", "old.py", "old.txt"])

    def test_added_secret_signatures_are_critical(self):
        diff = (
            "diff --git a/config.py b/config.py\n"
            "--- a/config.py\n+++ b/config.py\n"
            "@@ -1,0 +1 @@\n"
            "+TOKEN = \"ghp_abcdefghijklmnopqrstuvwxyz1234567890\"\n"
        )
        findings = scan_added_lines(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "critical")
        self.assertEqual(findings[0].code, "github-token")

    def test_risky_added_execution_patterns_are_high(self):
        diff = (
            "diff --git a/setup.sh b/setup.sh\n"
            "--- a/setup.sh\n+++ b/setup.sh\n"
            "@@ -1,0 +1 @@\n"
            "+curl https://example.invalid/install.sh | sh\n"
        )
        findings = scan_added_lines(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "high")
        self.assertEqual(findings[0].code, "shell-pipe-to-interpreter")

    def test_removed_unsafe_lines_do_not_trigger_added_line_scan(self):
        diff = (
            "diff --git a/setup.sh b/setup.sh\n"
            "--- a/setup.sh\n+++ b/setup.sh\n"
            "@@ -1 +0,0 @@\n"
            "-curl https://example.invalid/install.sh | sh\n"
        )
        self.assertEqual(scan_added_lines(diff), [])

    def test_hidden_control_plane_path_is_not_normalized_away(self):
        finding = classify_changed_path(".github/workflows/release.yml")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.code, "protected-control-plane-change")

    def test_clean_documentation_path_is_not_flagged(self):
        self.assertIsNone(classify_changed_path("docs/AI_REVIEW.md"))



class NativeReviewerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Streamiov Test")
        self.git("config", "user.email", "test@streamiov.invalid")
        self.git("branch", "-M", "main")
        (self.root / "README.md").write_text("baseline\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "baseline")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "src").mkdir()
        (self.root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests/test_app.py").write_text(
            "import unittest\nclass AppTests(unittest.TestCase):\n"
            "    def test_value(self):\n        self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )
        self.git("add", "src/app.py", "tests/test_app.py")
        self.git("commit", "-q", "-m", "add app and tests")
        self.head = self.git("rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def test_reviews_exact_head_and_runs_only_fixed_test_suite(self):
        report = review_repository(self.root, self.base, self.head, run_tests=True)
        self.assertEqual(report.decision, "pass", report.to_dict())
        self.assertEqual(report.test_result["status"], "passed")
        self.assertIn("src/app.py", report.changed_files)
        self.assertIn("tests/test_app.py", report.changed_files)

    def test_refuses_to_run_tests_for_a_different_checked_out_head(self):
        self.git("checkout", "-q", self.base)
        report = review_repository(self.root, self.base, self.head, run_tests=True)
        self.assertEqual(report.decision, "reject")
        self.assertEqual(report.test_result["status"], "wrong-worktree")


if __name__ == "__main__":
    unittest.main()
