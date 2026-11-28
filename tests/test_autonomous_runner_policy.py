"""Regression tests for the trusted AI Chief mission policy."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.autonomous.run_issue import clear_verified_local_provider_cooldown


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "autonomous" / "run_issue.py"


class AutonomousRunnerPolicyTests(unittest.TestCase):
    def test_long_owner_issue_is_accepted_and_context_fit_preserves_final_criteria(self):
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        constants = {
            node.targets[0].id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        }
        self.assertEqual(constants["MAX_ISSUE_BODY_CHARS"], 20000)
        self.assertEqual(constants["MAX_MISSION_GOAL_CHARS"], 8000)
        helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "fit_issue_body")
        helper_source = ast.unparse(helper)
        self.assertIn("body[-tail:]", helper_source)
        self.assertIn("body[:head]", helper_source)
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        self.assertIn("MAX_ISSUE_BODY_CHARS", ast.unparse(main))

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

    def test_local_provider_cooldown_reset_is_schema_safe_and_mission_scoped(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "missions.sqlite3"
            with patch.dict(os.environ, {"STREAMIOV_MODEL_PROVIDERS": "ollama"}):
                self.assertFalse(clear_verified_local_provider_cooldown(database, "active-mission"))
                with sqlite3.connect(database) as db:
                    db.execute(
                        """CREATE TABLE development_missions (
                           mission_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                           planning_retry_at REAL, planning_failures INTEGER NOT NULL DEFAULT 0,
                           planning_owner TEXT NOT NULL DEFAULT '',
                           planning_lease_until REAL
                        )"""
                    )
                    db.executemany(
                        """INSERT INTO development_missions
                           (mission_id,status,planning_retry_at,planning_failures,planning_owner,planning_lease_until)
                           VALUES(?,?,?,?,?,?)""",
                        [
                            ("active-mission", "active", 9999.0, 4, "worker", 123.0),
                            ("other-mission", "active", 8888.0, 3, "other", 456.0),
                            ("completed-mission", "completed", 7777.0, 2, "old", 789.0),
                        ],
                    )
                self.assertTrue(clear_verified_local_provider_cooldown(database, "active-mission"))
                with sqlite3.connect(database) as db:
                    rows = {
                        row[0]: row[1:]
                        for row in db.execute(
                            """SELECT mission_id, planning_retry_at, planning_failures,
                               planning_owner, planning_lease_until FROM development_missions"""
                        ).fetchall()
                    }
                self.assertEqual(rows["active-mission"], (None, 0, "", None))
                self.assertEqual(rows["other-mission"], (8888.0, 3, "other", 456.0))
                self.assertEqual(rows["completed-mission"], (7777.0, 2, "old", 789.0))

                with sqlite3.connect(database) as db:
                    db.execute(
                        """UPDATE development_missions SET planning_retry_at=9999.0
                           WHERE mission_id='active-mission'"""
                    )
                with patch.dict(os.environ, {"STREAMIOV_MODEL_PROVIDERS": "cloudflare-workers-ai"}):
                    self.assertFalse(clear_verified_local_provider_cooldown(database, "active-mission"))
                with sqlite3.connect(database) as db:
                    retry_at = db.execute(
                        "SELECT planning_retry_at FROM development_missions WHERE mission_id='active-mission'"
                    ).fetchone()[0]
                self.assertEqual(retry_at, 9999.0)

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

    def test_agent_factory_forwards_task_id_to_project_tool_leases(self):
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "DevelopmentAgent"
        ]
        self.assertTrue(any(
            any(
                keyword.arg == "task_id"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "task_id"
                for keyword in call.keywords
            )
            for call in calls
        ))
        lambdas = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Lambda)
            and any(argument.arg == "role" for argument in node.args.args)
        ]
        self.assertTrue(any(
            any(argument.arg == "task_id" for argument in node.args.args)
            for node in lambdas
        ))

    def test_mission_runner_exports_checkpoint_counts_for_auditable_status(self):
        source = (ROOT / "scripts" / "autonomous" / "run_issue.py").read_text(encoding="utf-8")
        for field in ("status", "mission_id", "cycle", "pending_tasks", "running_tasks", "completed_tasks", "failed_tasks", "attempts"):
            with self.subTest(field=field):
                self.assertIn(f'output.write(f"{field}=', source)

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
