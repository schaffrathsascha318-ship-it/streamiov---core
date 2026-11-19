import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "native-reviewer.yml"


class NativeReviewerWorkflowTests(unittest.TestCase):
    def test_runs_on_pull_request_with_read_only_permissions(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", source)
        self.assertNotIn("\n  pull_request:\n", source)
        self.assertIn("contents: read", source)
        self.assertIn("pull-requests: read", source)
        self.assertNotIn("contents: write", source)
        self.assertNotIn("pull-requests: write", source)

    def test_executes_reviewer_from_trusted_base_revision(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", source)
        self.assertIn("refs/pull/${PR_NUMBER}/head:refs/remotes/pull/${PR_NUMBER}/head", source)
        self.assertIn("python -m ai.review.independent_reviewer", source)
        self.assertIn('--base "$BASE_SHA"', source)
        self.assertIn('--head "$HEAD_REF"', source)
        self.assertNotIn("ref: ${{ github.event.pull_request.head.sha }}", source)

    def test_does_not_checkout_or_execute_untrusted_pull_request_code(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("without checking out or executing PR code", source)
        self.assertNotIn("npm install", source)
        self.assertNotIn("npm test", source)
        self.assertNotIn("--run-tests", source)
        self.assertIn("pull_request_target", source)

    def test_publishes_structured_report_to_the_actions_summary(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("--json-out", source)
        self.assertIn("GITHUB_STEP_SUMMARY", source)
        self.assertIn("streamiov-native-review.json", source)


if __name__ == "__main__":
    unittest.main()
