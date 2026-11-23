import unittest

from ai.game_studio.quality import (
    QualityReportError,
    build_correction_queue,
    evaluate_release_gate,
)


def finding(fid="F-1", severity="major"):
    return {
        "id": fid,
        "severity": severity,
        "description": "Player can get stuck after a failed jump.",
        "location": "scenes/level_01.tscn",
        "reproduction": "Repeat jump into the west wall.",
        "expected_result": "Player returns to a controllable state.",
        "recommended_correction": "Fix collision recovery and add regression coverage.",
        "evidence": ["test-log:42"],
    }


def report(role, reviewer, findings=None, snapshot="snapshot-123"):
    return {
        "reviewer_role": role,
        "reviewer_id": reviewer,
        "project_snapshot": snapshot,
        "findings": findings or [],
    }


class GameQualityGateTests(unittest.TestCase):
    def setUp(self):
        self.self_report = report("game_builder_self_review", "game-agent", [finding()])
        self.dev_report = report("independent_developer_review", "developer-agent", [])

    def test_creates_correction_queue_with_separate_reviewers(self):
        queue = build_correction_queue(self.self_report, self.dev_report)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["correction_status"], "PENDING")
        self.assertEqual(queue[0]["write_scope"], "isolated_work_branch_or_snapshot")

    def test_rejects_same_reviewer_identity(self):
        same = report("independent_developer_review", "game-agent", [])
        with self.assertRaises(QualityReportError):
            build_correction_queue(self.self_report, same)

    def test_rejects_different_project_snapshots(self):
        other = report("independent_developer_review", "developer-agent", [], "other")
        with self.assertRaises(QualityReportError):
            build_correction_queue(self.self_report, other)

    def test_release_gate_stays_closed_without_evidence(self):
        result = evaluate_release_gate(
            self.self_report, self.dev_report,
            correction_records=[],
            automated_tests={"status": "passed", "run_ref": "ci:123"},
            gameplay_evidence={"status": "passed", "device_test_refs": ["device:1"], "completed_playthrough_ref": "play:1"},
            rights_review={"status": "approved", "review_ref": "rights:1"},
        )
        self.assertFalse(result["release_ready"])
        self.assertEqual(result["status"], "NEEDS_REVIEW")

    def test_release_gate_requires_verified_fix_diff_and_regression_test(self):
        result = evaluate_release_gate(
            self.self_report, self.dev_report,
            correction_records=[{"finding_id": "F-1", "status": "verified", "diff_ref": "diff:1", "regression_test_ref": "test:1"}],
            automated_tests={"status": "passed", "run_ref": "ci:123"},
            gameplay_evidence={"status": "passed", "device_test_refs": ["device:1"], "completed_playthrough_ref": "play:1"},
            rights_review={"status": "approved", "review_ref": "rights:1"},
        )
        self.assertTrue(result["release_ready"])
        self.assertEqual(result["status"], "RELEASE_REVIEW_READY")


if __name__ == "__main__":
    unittest.main()
