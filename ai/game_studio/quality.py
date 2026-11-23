"""Evidence-based, two-pass quality gate for AI-produced games.

Self-review and independent developer review are deliberately separate.
This module records review outcomes; it does not claim to execute gameplay
or certify devices. Evidence must be supplied by the corresponding test tools.
"""
from __future__ import annotations

from typing import Any

SEVERITIES = {"blocker", "critical", "major", "minor", "suggestion"}
OPEN_RELEASE_BLOCKERS = {"blocker", "critical"}


class QualityReportError(ValueError):
    """Raised when a review report is malformed or falsely self-approved."""


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QualityReportError(f"{field} must be non-empty text.")
    return value.strip()


def validate_review_report(report: dict[str, Any], expected_role: str) -> dict[str, Any]:
    """Validate one review pass and normalize its findings."""
    if not isinstance(report, dict):
        raise QualityReportError("Review report must be an object.")
    role = _require_text(report.get("reviewer_role"), "reviewer_role")
    if role != expected_role:
        raise QualityReportError(f"Expected reviewer_role {expected_role!r}.")
    reviewer_id = _require_text(report.get("reviewer_id"), "reviewer_id")
    project_snapshot = _require_text(report.get("project_snapshot"), "project_snapshot")
    findings = report.get("findings")
    if not isinstance(findings, list):
        raise QualityReportError("findings must be an array.")

    normalized = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise QualityReportError(f"findings[{index}] must be an object.")
        severity = _require_text(finding.get("severity"), f"findings[{index}].severity").lower()
        if severity not in SEVERITIES:
            raise QualityReportError(f"Unsupported severity: {severity}")
        finding_id = _require_text(finding.get("id"), f"findings[{index}].id")
        description = _require_text(finding.get("description"), f"findings[{index}].description")
        location = _require_text(finding.get("location"), f"findings[{index}].location")
        reproduction = _require_text(finding.get("reproduction"), f"findings[{index}].reproduction")
        expected = _require_text(finding.get("expected_result"), f"findings[{index}].expected_result")
        correction = _require_text(finding.get("recommended_correction"), f"findings[{index}].recommended_correction")
        evidence = finding.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(item, str) or not item.strip() for item in evidence):
            raise QualityReportError(f"findings[{index}].evidence must be an array of non-empty references.")
        normalized.append({
            "id": finding_id,
            "severity": severity,
            "description": description,
            "location": location,
            "reproduction": reproduction,
            "expected_result": expected,
            "recommended_correction": correction,
            "evidence": evidence,
            "status": "OPEN",
        })

    return {
        "reviewer_role": role,
        "reviewer_id": reviewer_id,
        "project_snapshot": project_snapshot,
        "findings": normalized,
        "reviewed": True,
    }


def build_correction_queue(*reports: dict[str, Any]) -> list[dict[str, Any]]:
    """Create auditable correction tasks from self-review and developer review."""
    if len(reports) != 2:
        raise QualityReportError("Exactly one self-review and one developer review are required.")
    self_review = validate_review_report(reports[0], "game_builder_self_review")
    developer_review = validate_review_report(reports[1], "independent_developer_review")
    if self_review["reviewer_id"] == developer_review["reviewer_id"]:
        raise QualityReportError("The independent reviewer must differ from the game builder.")
    if self_review["project_snapshot"] != developer_review["project_snapshot"]:
        raise QualityReportError("Both reviewers must inspect the same immutable project snapshot.")

    queue = []
    for source in (self_review, developer_review):
        for finding in source["findings"]:
            queue.append({
                **finding,
                "reported_by": source["reviewer_role"],
                "correction_status": "PENDING",
                "requires_regression_test": True,
                "write_scope": "isolated_work_branch_or_snapshot",
            })
    return queue


def evaluate_release_gate(
    self_report: dict[str, Any],
    developer_report: dict[str, Any],
    *,
    correction_records: list[dict[str, Any]],
    automated_tests: dict[str, Any],
    gameplay_evidence: dict[str, Any],
    rights_review: dict[str, Any],
) -> dict[str, Any]:
    """Return a conservative gate decision; missing evidence always blocks."""
    queue = build_correction_queue(self_report, developer_report)
    if not isinstance(correction_records, list):
        raise QualityReportError("correction_records must be an array.")

    correction_map = {}
    for record in correction_records:
        if not isinstance(record, dict):
            raise QualityReportError("Each correction record must be an object.")
        finding_id = _require_text(record.get("finding_id"), "correction finding_id")
        if finding_id in correction_map:
            raise QualityReportError(f"Duplicate correction record: {finding_id}")
        correction_map[finding_id] = record

    unresolved = []
    for finding in queue:
        record = correction_map.get(finding["id"])
        if not record or record.get("status") != "verified":
            unresolved.append(finding["id"])
            continue
        if not record.get("diff_ref") or not record.get("regression_test_ref"):
            unresolved.append(finding["id"])

    open_critical = [
        finding["id"] for finding in queue
        if finding["severity"] in OPEN_RELEASE_BLOCKERS and finding["id"] in unresolved
    ]
    tests_passed = (
        isinstance(automated_tests, dict)
        and automated_tests.get("status") == "passed"
        and bool(automated_tests.get("run_ref"))
    )
    gameplay_passed = (
        isinstance(gameplay_evidence, dict)
        and gameplay_evidence.get("status") == "passed"
        and bool(gameplay_evidence.get("device_test_refs"))
        and bool(gameplay_evidence.get("completed_playthrough_ref"))
    )
    rights_passed = (
        isinstance(rights_review, dict)
        and rights_review.get("status") == "approved"
        and bool(rights_review.get("review_ref"))
    )

    ready = not unresolved and tests_passed and gameplay_passed and rights_passed
    return {
        "status": "RELEASE_REVIEW_READY" if ready else "NEEDS_REVIEW",
        "release_ready": ready,
        "open_findings": unresolved,
        "open_blocker_or_critical_findings": open_critical,
        "independent_review_confirmed": True,
        "automated_tests_passed": tests_passed,
        "real_gameplay_and_device_evidence_present": gameplay_passed,
        "rights_review_approved": rights_passed,
        "missing_gates": [
            name for name, passed in (
                ("verified_corrections_with_diff_and_regression_tests", not unresolved),
                ("automated_tests", tests_passed),
                ("real_gameplay_and_device_evidence", gameplay_passed),
                ("rights_and_asset_review", rights_passed),
            ) if not passed
        ],
    }
