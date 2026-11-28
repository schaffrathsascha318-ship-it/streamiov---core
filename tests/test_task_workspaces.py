from contextlib import closing
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ai.core.orchestrator import SpecialistTask
from ai.runtime.continuous_engine import ContinuousDevelopmentEngine, MissionPlan
from ai.runtime.project_tools import ProjectTools
from ai.runtime.task_workspaces import TaskWorkspaceError, TaskWorkspaceStore


class SequencePlanner:
    def __init__(self, plans):
        self.plans = list(plans)

    def plan(self, goal, progress, *, mission_id, cycle):
        return self.plans.pop(0)


class TaskWorkspaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "file.txt").write_text("base\n", encoding="utf-8")
        self.db = self.base / "missions.sqlite3"
        self.store = TaskWorkspaceStore(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def _ensure(self, task_id="mission:1:code", worker="worker-a", lease=300):
        return self.store.ensure_workspace(
            task_id, "mission", 1, self.source, worker, lease,
        )

    def _tools(self, workspace, task_id="mission:1:code"):
        tools = ProjectTools(workspace, full_project_development=True, task_id=task_id)
        tools.workspace_store = self.store
        tools.workspace_task_id = task_id
        return tools

    def test_changes_survive_deleted_workspace_directory(self):
        workspace, rebuilt = self._ensure()
        self.assertTrue(rebuilt)
        tools = self._tools(workspace)
        tools.replace_text("file.txt", "base", "recovered")
        self.assertEqual((workspace / "file.txt").read_text(encoding="utf-8"), "recovered\n")
        self.assertEqual(self.store.change_count("mission:1:code"), 1)

        shutil.rmtree(workspace)
        recovered, rebuilt_again = self._ensure()
        self.assertTrue(rebuilt_again)
        self.assertEqual(recovered, workspace)
        self.assertEqual((recovered / "file.txt").read_text(encoding="utf-8"), "recovered\n")

    def test_repeated_edits_keep_original_source_base(self):
        workspace, _ = self._ensure()
        tools = self._tools(workspace)
        tools.replace_text("file.txt", "base", "first")
        tools.replace_text("file.txt", "first", "second")
        with closing(self.store._connect()) as db:
            row = db.execute(
                "SELECT * FROM development_task_workspace_changes WHERE task_id=? AND relative_path=?",
                ("mission:1:code", "file.txt"),
            ).fetchone()
        self.assertEqual(row["base_sha256"], "f34848ca92665c342abd5816c9e3eda0e82180671195362bcd0080544a3bc2ac")
        self.assertEqual(row["content"], "second\n")

    def test_pending_write_is_promoted_when_physical_file_matches(self):
        workspace, _ = self._ensure()
        self.store.begin_change("mission:1:code", "new.txt", "", "pending\n")
        (workspace / "new.txt").write_text("pending\n", encoding="utf-8")
        shutil.rmtree(workspace)
        recovered, _ = self._ensure()
        self.assertEqual((recovered / "new.txt").read_text(encoding="utf-8"), "pending\n")
        with closing(self.store._connect()) as db:
            status = db.execute(
                "SELECT status FROM development_task_workspace_changes WHERE task_id=? AND relative_path=?",
                ("mission:1:code", "new.txt"),
            ).fetchone()[0]
        self.assertEqual(status, "applied")

    def test_expired_lease_marks_workspace_orphaned_without_deleting_changes(self):
        workspace, _ = self._ensure(lease=10)
        self._tools(workspace).replace_text("file.txt", "base", "orphan-safe")
        self.assertEqual(self.store.recover_expired_leases(time.time() + 30), 1)
        status = self.store.workspace_status("mission:1:code")
        self.assertEqual(status["status"], "orphaned")
        self.assertEqual(status["owner_worker_id"], "")
        self.assertEqual(self.store.change_count("mission:1:code"), 1)

    def test_protected_and_traversal_paths_are_rejected(self):
        self._ensure()
        for path in ("../escape.txt", "/absolute.txt", ".env", "secrets/token.txt", "auth.json"):
            with self.subTest(path=path), self.assertRaises(TaskWorkspaceError):
                self.store.begin_change("mission:1:code", path, "", "blocked\n")

    def test_verified_candidate_integrates_ready_changes_only(self):
        first, _ = self._ensure("mission:1:code")
        self._tools(first, "mission:1:code").replace_text("file.txt", "base", "ready")
        self.store.mark_task_status("mission:1:code", "ready", "pending")

        second, _ = self.store.ensure_workspace(
            "mission:1:research", "mission", 1, self.source, "worker-b", 300,
        )
        self._tools(second, "mission:1:research").write_file("failed.txt", "not integrated\n")
        self.store.mark_task_status("mission:1:research", "blocked", "conflict")

        candidate = self.store.build_candidate("mission", 1, self.source)
        self.assertEqual(candidate["status"], "building")
        self.assertEqual(candidate["changes"], 1)
        integration = self.store.integrate_candidate("mission", 1)
        self.assertTrue(integration["ok"])
        self.assertEqual((self.source / "file.txt").read_text(encoding="utf-8"), "ready\n")
        self.assertFalse((self.source / "failed.txt").exists())
        self.assertEqual(
            self.store.workspace_status("mission:1:code")["integration_status"], "integrated",
        )

    def test_latest_integration_requires_an_explicitly_verified_candidate(self):
        workspace, _ = self._ensure("mission:1:code")
        self._tools(workspace, "mission:1:code").replace_text("file.txt", "base", "ready")
        self.store.mark_task_status("mission:1:code", "ready", "pending")
        self.store.build_candidate("mission", 1, self.source)

        pending = self.store.integrate_latest_candidate("mission")
        self.assertTrue(pending["missing"])
        self.assertEqual((self.source / "file.txt").read_text(encoding="utf-8"), "base\n")

        self.store.mark_candidate_status("mission", 1, "verified")
        integrated = self.store.integrate_latest_candidate("mission")
        self.assertTrue(integrated["ok"])
        self.assertEqual((self.source / "file.txt").read_text(encoding="utf-8"), "ready\n")

    def test_candidate_collects_unintegrated_changes_across_cycles(self):
        first, _ = self._ensure("mission:1:code")
        self._tools(first, "mission:1:code").replace_text("file.txt", "base", "cycle-one")
        self.store.mark_task_status("mission:1:code", "ready", "pending")

        second, _ = self.store.ensure_workspace(
            "mission:2:docs", "mission", 2, self.source, "worker-b", 300,
        )
        self._tools(second, "mission:2:docs").write_file("notes.txt", "cycle two\n")
        self.store.mark_task_status("mission:2:docs", "ready", "pending")

        candidate = self.store.build_candidate("mission", 2, self.source)
        self.assertEqual(candidate["changes"], 2)
        integration = self.store.integrate_candidate("mission", 2)
        self.assertTrue(integration["ok"])
        self.assertEqual((self.source / "file.txt").read_text(encoding="utf-8"), "cycle-one\n")
        self.assertEqual((self.source / "notes.txt").read_text(encoding="utf-8"), "cycle two\n")

    def test_source_mutation_blocks_integration_without_overwrite(self):
        workspace, _ = self._ensure()
        self._tools(workspace).replace_text("file.txt", "base", "task-change")
        self.store.mark_task_status("mission:1:code", "ready", "pending")
        self.store.build_candidate("mission", 1, self.source)
        (self.source / "file.txt").write_text("external-change\n", encoding="utf-8")

        integration = self.store.integrate_candidate("mission", 1)
        self.assertFalse(integration["ok"])
        self.assertTrue(any("changed in the shared source" in item for item in integration["conflicts"]))
        self.assertEqual((self.source / "file.txt").read_text(encoding="utf-8"), "external-change\n")
        self.assertEqual(
            self.store.workspace_status("mission:1:code")["integration_status"], "conflict",
        )

    def test_overlapping_task_changes_block_candidate_integration(self):
        first, _ = self._ensure("mission:1:code")
        self._tools(first, "mission:1:code").replace_text("file.txt", "base", "from-code")
        self.store.mark_task_status("mission:1:code", "ready", "pending")
        second, _ = self.store.ensure_workspace(
            "mission:1:research", "mission", 1, self.source, "worker-b", 300,
        )
        self._tools(second, "mission:1:research").replace_text("file.txt", "base", "from-research")
        self.store.mark_task_status("mission:1:research", "ready", "pending")

        candidate = self.store.build_candidate("mission", 1, self.source)
        self.assertEqual(candidate["status"], "blocked")
        self.assertIn("Multiple tasks changed the same file", candidate["conflict"])
        self.assertFalse(self.store.integrate_candidate("mission", 1)["ok"])
        self.assertEqual((self.source / "file.txt").read_text(encoding="utf-8"), "base\n")


class EngineWorkspaceIntegrationTests(unittest.TestCase):
    def test_engine_isolates_task_writes_and_integrates_after_verification(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        source = base / "source"
        source.mkdir()
        (source / "file.txt").write_text("base\n", encoding="utf-8")
        database = base / "mission.sqlite3"

        class WorkspaceAgent:
            def __init__(self, role):
                self.role = role
                self.tools = ProjectTools(source, full_project_development=True)

            def run(self, prompt, **kwargs):
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return json.dumps({
                        "passed": True,
                        "findings": [],
                        "tool_evidence": [
                            {"tool": "run_tests", "result": "exit_code=0\nOK"}
                        ],
                    })
                self.tools.replace_text("file.txt", "base", "implemented")
                return f"{self.role} changed its isolated workspace"

        planner = SequencePlanner([
            MissionPlan("continue", "Implement in an isolated workspace.", (
                SpecialistTask("isolated-code", "code", "Change the file in your task workspace."),
            )),
            MissionPlan("completed", "Implementation finished; verification is required."),
            MissionPlan("completed", "Verified and integrated."),
        ])
        engine = ContinuousDevelopmentEngine(database, planner, WorkspaceAgent)
        mission_id = engine.create_mission("Verify isolated workspaces and safe integration")
        snapshot = engine.run(mission_id, threading.Event(), poll_seconds=0.01)

        self.assertEqual(snapshot.status, "completed")
        self.assertEqual((source / "file.txt").read_text(encoding="utf-8"), "implemented\n")
        self.assertIsNotNone(engine.workspaces)


if __name__ == "__main__":
    unittest.main()
