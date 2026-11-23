"""Native, provider-free review engine for Streamiov source changes.

The reviewer is deliberately deterministic and read-only. It uses Git diffs,
Python's AST parser, and a fixed local policy; it never calls a model endpoint,
network service, shell supplied by a patch, or third-party review API.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, field
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


REVIEWER_VERSION = "1.0.0"
DEFAULT_TEST_TIMEOUT_SECONDS = 900
MAX_DIFF_BYTES = 2_000_000
MAX_CHANGED_FILES = 500

SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("cloud-provider-secret", re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|access[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{24,}['\"]")),
)
UNSAFE_PATTERNS = (
    ("shell-pipe-to-interpreter", re.compile(r"(?i)\b(?:curl|wget)\b[^\n|]*\|\s*(?:sh|bash|zsh)\b")),
    ("disabled-tls-verification", re.compile(r"(?i)(?:verify\s*=\s*False|rejectUnauthorized\s*:\s*false)")),
    ("world-writable-permissions", re.compile(r"(?i)\bchmod\s+(?:-R\s+)?777\b")),
    ("dynamic-eval", re.compile(r"(?i)\beval\s*\(")),
    ("unsafe-deserialization", re.compile(r"\bpickle\.loads\s*\(")),
    ("unapproved-ai-provider-import", re.compile(r"(?i)^\s*(?:from|import)\s+(?:openai|anthropic|cohere|mistralai|replicate|together|groq|google\.generativeai|google\.genai)\b")),
    ("unapproved-ai-provider-endpoint", re.compile(r"(?i)\b(?:api\.openai\.com|api\.anthropic\.com|api\.cohere\.com|api\.mistral\.ai|api\.groq\.com|generativelanguage\.googleapis\.com)\b")),
    ("unapproved-ai-provider-package", re.compile(r"(?i)[\"']?(?:openai|anthropic|cohere|mistralai|replicate|together|groq|google-generativeai)[\"']?\s*[:@]")),
)
PROTECTED_PATH_PREFIXES = (
    ".github/workflows/",
    ".github/actions/",
    "scripts/autonomous/",
    "scripts/deploy/",
    "ai/providers/",
    "ai/security/",
    "ai/review/",
)
PROTECTED_FILE_NAMES = {
    "wrangler.toml", "wrangler.jsonc", "client_secret.json",
    "credentials.json", "token.json", "tokens.json", "oauth.json",
    "auth.json", "tiktok-oauth.js", "twitch-oauth.js", "continuous_engine.py", "project_tools.py", "agent.py",
}
SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
TEST_PATH_PARTS = {"test", "tests", "__tests__", "spec"}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    line: int | None
    message: str


@dataclass
class ReviewReport:
    base: str
    head: str
    reviewer_version: str = REVIEWER_VERSION
    changed_files: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    test_result: dict | None = None
    decision: str = "pass"

    def finalize(self) -> "ReviewReport":
        levels = {item.severity for item in self.findings}
        if "critical" in levels:
            self.decision = "reject"
        elif "high" in levels:
            self.decision = "needs_attention"
        elif levels:
            self.decision = "pass_with_warnings"
        else:
            self.decision = "pass"
        if self.test_result and self.test_result.get("status") != "passed":
            self.decision = "reject"
        return self

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["findings"] = [asdict(item) for item in self.findings]
        payload["counts"] = {
            severity: sum(1 for item in self.findings if item.severity == severity)
            for severity in ("critical", "high", "medium", "low")
        }
        return payload


def classify_changed_path(path: str) -> Finding | None:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    lowered = normalized.lower()
    name = lowered.rsplit("/", 1)[-1]
    path_parts = set(lowered.split("/"))
    adapter_segments = {"adapter", "adapters", "integration", "integrations", "platform", "platforms"}
    unsupported_platforms = {"obs", "youtube", "kick", "facebook"}
    if path_parts & adapter_segments and path_parts & unsupported_platforms:
        return Finding(
            "high", "unsupported-platform-adapter", normalized, None,
            "Only TikTok LIVE and Twitch LIVE adapters are approved; this path introduces a prohibited platform adapter.",
        )

    if name in PROTECTED_FILE_NAMES or any(
        lowered == prefix.rstrip("/") or lowered.startswith(prefix)
        for prefix in PROTECTED_PATH_PREFIXES
    ):
        return Finding(
            "high", "protected-control-plane-change", normalized, None,
            "A protected workflow, runner, provider, security, or deployment surface changed. "
            "This requires a dedicated policy review; the native reviewer will not silently approve it.",
        )
    if any(part.startswith(".env") for part in lowered.split("/")):
        return Finding("critical", "environment-file-change", normalized, None,
                      "Environment files may contain credentials and are not accepted in autonomous changes.")
    if lowered.endswith((".pem", ".key", ".p12", ".pfx")):
        return Finding("critical", "private-credential-file-change", normalized, None,
                      "A private-key or credential container file changed.")
    return None


def scan_added_lines(diff_text: str) -> list[Finding]:
    findings: list[Finding] = []
    current_path = ""
    new_line = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            new_line = 0
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?\s+@@", line)
            if match:
                new_line = int(match.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added = line[1:]
            for code, pattern in SECRET_PATTERNS:
                if pattern.search(added):
                    findings.append(Finding(
                        "critical", code, current_path, new_line,
                        "A newly added line matches a credential or private-key signature.",
                    ))
            for code, pattern in UNSAFE_PATTERNS:
                if pattern.search(added):
                    findings.append(Finding(
                        "high", code, current_path, new_line,
                        "A newly added line matches a risky execution or transport pattern.",
                    ))
            new_line += 1
        elif not line.startswith("-") and not line.startswith("\\"):
            if line and not line.startswith("diff --git"):
                new_line += 1
    return findings


def parse_name_status(output: str) -> list[str]:
    changed: list[str] = []
    for row in output.splitlines():
        if not row:
            continue
        fields = row.split("\t")
        status = fields[0]
        if status.startswith(("R", "C")):
            if len(fields) >= 3:
                changed.extend(fields[1:3])
        elif len(fields) >= 2:
            changed.append(fields[1])
    return sorted(set(changed))


def _git(root: Path, *args: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=timeout, check=False,
        env={"PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
             "HOME": "", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:1200]
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {detail}")
    return result.stdout


def _is_test_path(path: str) -> bool:
    parts = {part.lower() for part in Path(path).parts}
    stem = Path(path).stem.lower()
    return bool(parts & TEST_PATH_PARTS) or stem.startswith(("test_", "test-")) or stem.endswith(("_test", ".test", ".spec"))


def review_repository(
    root: str | Path,
    base: str,
    head: str,
    *,
    run_tests: bool = False,
    test_timeout: int = DEFAULT_TEST_TIMEOUT_SECONDS,
) -> ReviewReport:
    project = Path(root).resolve()
    if not (project / ".git").exists():
        raise ValueError("Review root must be a Git working tree.")
    if not base or not head or base.startswith("-") or head.startswith("-"):
        raise ValueError("Both base and head must be explicit Git refs.")
    base_commit = _git(project, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
    head_commit = _git(project, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    _git(project, "merge-base", base_commit, head_commit)

    report = ReviewReport(base=base_commit, head=head_commit)
    raw_names = _git(project, "diff", "--name-status", "--no-renames", f"{base}...{head}")
    report.changed_files = parse_name_status(raw_names)
    if len(report.changed_files) > MAX_CHANGED_FILES:
        report.findings.append(Finding(
            "critical", "diff-too-large", "", None,
            f"Change set exceeds the review limit of {MAX_CHANGED_FILES} files.",
        ))
        return report.finalize()
    if not report.changed_files:
        report.findings.append(Finding("medium", "empty-change-set", "", None,
                                      "No changed files were found between base and head."))
        return report.finalize()

    for path in report.changed_files:
        finding = classify_changed_path(path)
        if finding:
            report.findings.append(finding)

    diff = _git(project, "diff", "--no-ext-diff", "--unified=0", f"{base}...{head}")
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        report.findings.append(Finding("critical", "diff-byte-limit", "", None,
                                      f"Diff exceeds the {MAX_DIFF_BYTES}-byte review limit."))
        return report.finalize()
    report.findings.extend(scan_added_lines(diff))

    source_files = [path for path in report.changed_files if Path(path).suffix.lower() in SOURCE_SUFFIXES]
    test_files = [path for path in report.changed_files if _is_test_path(path)]
    if source_files and not test_files:
        report.findings.append(Finding(
            "medium", "missing-test-changes", "", None,
            "Source files changed without a corresponding test/spec file change. Verify coverage explicitly.",
        ))

    for path in report.changed_files:
        if Path(path).suffix.lower() != ".py" or path not in source_files:
            continue
        try:
            content = _git(project, "show", f"{head}:{path}")
            ast.parse(content, filename=path)
        except (SyntaxError, UnicodeDecodeError) as exc:
            report.findings.append(Finding(
                "critical", "python-syntax-error", path,
                getattr(exc, "lineno", None), f"Python source does not parse: {exc}",
            ))
        except RuntimeError as exc:
            if "does not exist" not in str(exc):
                report.findings.append(Finding("high", "source-read-failed", path, None, str(exc)))

    if run_tests:
        current_head = _git(project, "rev-parse", "HEAD").strip()
        requested_head = _git(project, "rev-parse", f"{head}^{{commit}}").strip()
        if current_head != requested_head:
            report.test_result = {
                "status": "wrong-worktree",
                "command": "python -m unittest discover -s tests -v",
                "exit_code": None,
                "summary": "Tests were not run because the checked-out worktree does not match the requested head commit.",
            }
            return report.finalize()
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
        try:
            result = subprocess.run(
                command, cwd=project, capture_output=True, text=True,
                timeout=test_timeout, check=False,
                env={"PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
                     "HOME": "", "PYTHONIOENCODING": "utf-8"},
            )
            report.test_result = {
                "status": "passed" if result.returncode == 0 else "failed",
                "command": "python -m unittest discover -s tests -v",
                "exit_code": result.returncode,
                "summary": (result.stdout + "\n" + result.stderr)[-6000:],
            }
        except subprocess.TimeoutExpired:
            report.test_result = {
                "status": "timeout",
                "command": "python -m unittest discover -s tests -v",
                "exit_code": None,
                "summary": f"Test run exceeded {test_timeout} seconds.",
            }
    return report.finalize()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Streamiov's native, provider-free code review.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--run-tests", action="store_true",
                        help="Run the fixed Python unittest suite; no arbitrary commands are accepted.")
    parser.add_argument("--test-timeout", type=int, default=DEFAULT_TEST_TIMEOUT_SECONDS)
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)
    if args.test_timeout < 1 or args.test_timeout > 3600:
        parser.error("--test-timeout must be between 1 and 3600 seconds.")
    try:
        report = review_repository(args.root, args.base, args.head,
                                   run_tests=args.run_tests, test_timeout=args.test_timeout)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"decision": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    payload = report.to_dict()
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.decision in {"pass", "pass_with_warnings"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
