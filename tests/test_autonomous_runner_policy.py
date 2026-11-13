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
        policy = ast.literal_eval(prefix_assignment.value)
        self.assertIn("weaken central permission enforcement", policy)
        self.assertIn("bypass required checks", policy)
        self.assertIn("identity and credential boundaries", policy)
        self.assertIn("untrusted task input", policy)


if __name__ == "__main__":
    unittest.main()
