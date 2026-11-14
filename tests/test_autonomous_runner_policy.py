"""Regression tests for the trusted AI Chief mission policy."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "autonomous" / "run_issue.py"


class AutonomousRunnerPolicyTests(unittest.TestCase):
    def test_chief_must_discover_and_implement_worthwhile_improvements(self):
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        build_task = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_task"
        )
        prefix_assignment = next(
            node for node in ast.walk(build_task)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "prefix" for target in node.targets)
        )
        policy = " ".join(
            node.value for node in ast.walk(prefix_assignment.value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        self.assertIn("identify missing capabilities", policy)
        self.assertIn("implement worthwhile improvements", policy)
        self.assertIn("highest-value unblocked work", policy)
        self.assertIn("reassess the roadmap", policy)

    def test_agent_runtime_and_providers_are_editable_but_permission_guard_is_protected(self):
        workflow = (ROOT / ".github" / "workflows" / "autonomous-development.yml").read_text(encoding="utf-8")
        guard = next(
            line for line in workflow.splitlines()
            if ".github/*|scripts/autonomous/" in line
        )
        self.assertNotIn("ai/core/agent.py", guard)
        self.assertNotIn("ai/providers/*", guard)
        self.assertNotIn("ai/runtime/continuous_engine.py", guard)
        self.assertIn("ai/runtime/project_tools.py", guard)
        self.assertIn("ai/*permissions*", guard)
        self.assertIn(".github/*", guard)

    def test_agent_branch_dispatches_ci_before_it_can_be_integrated(self):
        workflow = (ROOT / ".github" / "workflows" / "autonomous-development.yml").read_text(encoding="utf-8")
        self.assertIn("actions: write", workflow)
        self.assertIn("checks: read", workflow)
        self.assertIn("gh pr create --draft", workflow)
        self.assertIn("gh workflow run phase-1-agent-tests.yml --ref", workflow)
        self.assertIn("gh workflow run secret-scanning.yml --ref", workflow)
        self.assertIn("gh workflow run studio-build.yml --ref", workflow)
        self.assertIn("gh pr checks", workflow)
        self.assertIn("all(.[]; .state == \"SUCCESS\")", workflow)

    def test_self_improvement_does_not_authorize_bypassing_security(self):
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        build_task = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_task"
        )
        prefix_assignment = next(
            node for node in ast.walk(build_task)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "prefix" for target in node.targets)
        )
        policy = " ".join(
            node.value for node in ast.walk(prefix_assignment.value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        self.assertIn("weaken central permission enforcement", policy)
        self.assertIn("bypass required checks", policy)
        self.assertIn("identity and credential boundaries", policy)
        self.assertIn("untrusted task input", policy)


if __name__ == "__main__":
    unittest.main()
