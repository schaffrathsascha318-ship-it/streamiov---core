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

    def test_control_plane_and_security_guards_remain_protected(self):
        workflow = (ROOT / ".github" / "workflows" / "autonomous-development.yml").read_text(encoding="utf-8")
        guard = next(
            line for line in workflow.splitlines()
            if ".github/*|scripts/autonomous/" in line
        )
        self.assertIn(".github/*", guard)
        self.assertIn("scripts/autonomous/*", guard)
        self.assertIn("scripts/ai/*", guard)
        self.assertIn("ai/security/*", guard)
        self.assertIn("ai/*permissions*", guard)
        self.assertIn("*wrangler.toml", guard)
        self.assertNotIn("ai/core/agent.py", guard)
        self.assertNotIn("ai/providers/*", guard)
        self.assertNotIn("ai/runtime/continuous_engine.py", guard)
        self.assertNotIn("ai/runtime/project_tools.py", guard)

    def test_persistent_mission_enables_full_project_development(self):
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "DevelopmentAgent"
        ]
        self.assertTrue(calls)
        self.assertTrue(any(
            any(
                keyword.arg == "full_project_development"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in call.keywords
            )
            for call in calls
        ))

    def test_mission_runner_exports_checkpoint_counts_for_auditable_status(self):
        source = (ROOT / "scripts" / "autonomous" / "run_issue.py").read_text(encoding="utf-8")
        for field in ("status", "mission_id", "cycle", "pending_tasks", "running_tasks", "completed_tasks", "attempts"):
            with self.subTest(field=field):
                self.assertIn(f'output.write(f"{field}=', source)

    def test_agent_branch_dispatches_ci_and_keeps_draft_for_owner_approval(self):
        workflow = (ROOT / ".github" / "workflows" / "autonomous-development.yml").read_text(encoding="utf-8")
        self.assertIn("actions: write", workflow)
        self.assertIn("checks: read", workflow)
        self.assertIn("gh pr create --draft", workflow)
        self.assertIn("gh workflow run phase-1-agent-tests.yml --ref", workflow)
        self.assertIn("gh workflow run secret-scanning.yml --ref", workflow)
        self.assertIn("gh workflow run studio-build.yml --ref", workflow)
        self.assertIn("explicit owner approval", workflow)
        self.assertNotIn("gh pr merge", workflow)

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
