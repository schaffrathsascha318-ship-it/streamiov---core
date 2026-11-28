"""Shared parsing and validation for final verification reports."""
from __future__ import annotations

import re

EXIT_CODE_PATTERN = re.compile(r"^exit_code=(0|[1-9]\d*)(?:\s|$)")
INTERRUPTED_EXIT_CODE_PATTERN = re.compile(r"^exit_code=(-15|-9|124|137|143)(?:\s|$)")

VERIFICATION_REPORT_KEYS = frozenset({"passed", "findings"})
VERIFICATION_STORED_KEYS = frozenset({"passed", "findings", "tool_evidence"})
VAGUE_FINDINGS = frozenset({
    "all good",
    "failed",
    "keine fehler",
    "keine probleme",
    "looks good",
    "no errors detected",
    "no issues detected",
    "ok",
    "passed",
    "see above",
})
CONCRETE_FINDING_HINTS = (
    "abgeschlossen",
    "assertion",
    "command",
    "error",
    "evidence",
    "failed",
    "failing",
    "fehlt",
    "file",
    "finding",
    "findings",
    "incomplete",
    "integration",
    "invalid",
    "kein",
    "missing",
    "nicht",
    "nachgewiesen",
    "output",
    "path",
    "report",
    "result",
    "schema",
    "test",
    "tool",
    "traceback",
    "exception",
    "unbelegt",
    "unverified",
    "verifier",
)


class VerificationReportError(ValueError):
    pass


def observed_successful_test(output: object) -> bool:
    """Return True only when sanitized tool output starts with exit_code=0."""
    if not isinstance(output, str):
        return False
    match = EXIT_CODE_PATTERN.match(output.strip())
    return bool(match and int(match.group(1)) == 0)


def observed_interrupted_test(output: object) -> bool:
    """Return True when a tool run was terminated or timed out before completion."""
    if not isinstance(output, str):
        return False
    return bool(INTERRUPTED_EXIT_CODE_PATTERN.match(output.strip()))


def _is_concrete_finding(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 12 or text.casefold() in VAGUE_FINDINGS:
        return False
    lowered = text.casefold()
    return any(hint in lowered for hint in CONCRETE_FINDING_HINTS) or any(char.isdigit() for char in text)


def validate_verification_report(payload: object, *, stored: bool = False) -> None:
    expected = VERIFICATION_STORED_KEYS if stored else VERIFICATION_REPORT_KEYS
    if not isinstance(payload, dict) or set(payload) != expected:
        raise VerificationReportError(
            "Final verification report must be one JSON object with exactly "
            + "'passed' and 'findings'"
            + (" and 'tool_evidence'" if stored else "")
            + "; received keys: "
            + str(sorted(str(key) for key in payload) if isinstance(payload, dict) else type(payload).__name__)
        )
    if type(payload["passed"]) is not bool:
        raise VerificationReportError("The verification 'passed' field must be a JSON boolean.")
    findings = payload["findings"]
    if not isinstance(findings, list):
        raise VerificationReportError("The verification 'findings' field must be an array of concrete, non-empty strings.")
    for index, finding in enumerate(findings):
        if not _is_concrete_finding(finding):
            raise VerificationReportError(
                f"The verification 'findings[{index}]' field must describe a concrete, verifiable problem."
            )
    if payload["passed"] and findings:
        raise VerificationReportError("passed=true is invalid while findings remain; repair the findings and verify again.")
    if not payload["passed"] and not findings:
        raise VerificationReportError("passed=false is invalid without concrete findings describing what failed.")
    if stored:
        tool_evidence = payload["tool_evidence"]
        if not isinstance(tool_evidence, list):
            raise VerificationReportError("The verification 'tool_evidence' field must be an array.")
        for index, item in enumerate(tool_evidence):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("tool"), str)
                or not item["tool"].strip()
                or not isinstance(item.get("result"), str)
            ):
                raise VerificationReportError(
                    f"The verification 'tool_evidence[{index}]' field must contain a tool name and observed result."
                )
