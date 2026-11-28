import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

from ai.management.jason import JasonProjectAdministrator, JasonAdministrationError
from ai.__main__ import main
from ai.specialists import specialist_names


class JasonProjectAdministratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ai").mkdir()
        self.missions = self.root / "missions.sqlite3"
        self.queue = self.root / "queue.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_reports_specialists_project_areas_and_missing_databases_honestly(self):
        snapshot = JasonProjectAdministrator(
            self.root, mission_db=self.missions, queue_db=self.queue
        ).snapshot()
        self.assertEqual(snapshot["administrator"], "Jason")
        self.assertEqual(snapshot["technical_owner"], "AI Chief")
        self.assertEqual(snapshot["specialist_count"], len(specialist_names()))
        self.assertTrue(next(area for area in snapshot["project_areas"] if area["name"] == "ai")["present"])
        self.assertFalse(snapshot["missions"]["available"])
        self.assertFalse(snapshot["specialist_queue"]["available"])
        self.assertEqual(len(snapshot["blockers"]), 2)

    def test_reads_persistent_missions_and_specialist_assignments(self):
        with closing(sqlite3.connect(self.missions)) as db:
            db.executescript("""
                CREATE TABLE development_missions (
                    mission_id TEXT PRIMARY KEY, goal TEXT, status TEXT, cycle INTEGER,
                    summary TEXT, created_at REAL, updated_at REAL
                );
                CREATE TABLE development_mission_tasks (
                    task_id TEXT PRIMARY KEY, mission_id TEXT, specialist TEXT, status TEXT
                );
                INSERT INTO development_missions VALUES
                    ('mission-1', 'Complete Streamiov', 'active', 4, 'Working', 1, 2);
                INSERT INTO development_mission_tasks VALUES
                    ('task-1', 'mission-1', 'testing', 'succeeded');
                INSERT INTO development_mission_tasks VALUES
                    ('task-2', 'mission-1', 'studio', 'queued');
            """)
        with closing(sqlite3.connect(self.queue)) as db:
            db.executescript("""
                CREATE TABLE specialist_tasks (
                    specialist TEXT, status TEXT
                );
                INSERT INTO specialist_tasks VALUES ('studio', 'queued');
                INSERT INTO specialist_tasks VALUES ('studio', 'failed');
            """)
        snapshot = JasonProjectAdministrator(
            self.root, mission_db=self.missions, queue_db=self.queue
        ).snapshot()
        mission = snapshot["missions"]["missions"][0]
        self.assertEqual(mission["mission_id"], "mission-1")
        self.assertEqual(mission["tasks"]["succeeded"], 1)
        self.assertEqual(mission["tasks"]["queued"], 1)
        self.assertEqual(snapshot["missions"]["assignments"], [
            {"specialist": "studio", "status": "queued", "count": 1},
            {"specialist": "testing", "status": "succeeded", "count": 1},
        ])
        self.assertEqual(snapshot["active_mission_count"], 1)
        self.assertEqual(snapshot["specialist_queue"]["assignments"], [
            {"specialist": "studio", "status": "failed", "count": 1},
            {"specialist": "studio", "status": "queued", "count": 1},
        ])
        self.assertTrue(any("failed" in item for item in snapshot["blockers"]))

    def test_snapshot_is_json_serializable_and_authority_is_read_only(self):
        admin = JasonProjectAdministrator(self.root, mission_db=self.missions, queue_db=self.queue)
        snapshot = json.loads(admin.render_json())
        self.assertTrue(snapshot["authority"]["may_track_and_report"])
        self.assertFalse(snapshot["authority"]["may_assign_and_coordinate"])
        self.assertFalse(snapshot["authority"]["may_override_chief_technical_decisions"])
        self.assertFalse(snapshot["authority"]["may_deploy_or_change_production"])
        self.assertFalse(snapshot["authority"]["may_access_secrets_or_credentials"])

    def test_rejects_symlink_database(self):
        target = self.root / "real.sqlite3"
        with closing(sqlite3.connect(target)):
            pass
        link = self.root / "linked.sqlite3"
        link.symlink_to(target)
        with self.assertRaises(JasonAdministrationError):
            JasonProjectAdministrator(
                self.root, mission_db=link, queue_db=self.queue
            ).snapshot()

    def test_rejects_missing_project_root(self):
        with self.assertRaises(JasonAdministrationError):
            JasonProjectAdministrator(
                self.root / "missing", mission_db=self.missions, queue_db=self.queue
            )

    def test_cli_exposes_jason_status_as_json(self):
        output = StringIO()
        with redirect_stdout(output):
            code = main([
                "--jason-status",
                "--project-root", str(self.root),
                "--jason-mission-db", str(self.missions),
                "--jason-queue-db", str(self.queue),
            ])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["administrator"], "Jason")
        self.assertEqual(payload["specialist_count"], len(specialist_names()))
        self.assertEqual(payload["missions"]["database"], str(self.missions))


if __name__ == "__main__":
    unittest.main()
