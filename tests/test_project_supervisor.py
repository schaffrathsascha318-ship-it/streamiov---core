import json
import tempfile
import threading
import unittest
from pathlib import Path

from ai.runtime.continuous_engine import MissionEngineError, MissionSnapshot
from ai.runtime.project_supervisor import ProjectSupervisor, ProjectSupervisorError
from ai.__main__ import build_parser


class FakeMissionEngine:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.missions = {}
        self.created = []
        self.runs = []

    def create_mission(self, goal, *, mission_id=None):
        mission_id = mission_id or f"mission-{len(self.created) + 1}"
        if mission_id in self.missions:
            raise MissionEngineError("Mission ID already exists.")
        self.missions[mission_id] = MissionSnapshot(
            mission_id, goal, "active", 0, "", 0, 0, 0, 0, 0
        )
        self.created.append((mission_id, goal))
        return mission_id

    def get_mission(self, mission_id):
        if mission_id not in self.missions:
            raise MissionEngineError("Mission not found.")
        return self.missions[mission_id]

    def run(self, mission_id, stop_event, *, poll_seconds, emit, worker_id):
        self.runs.append(mission_id)
        outcome = self.outcomes.pop(0)
        status, should_stop = outcome[:2]
        summary = outcome[2] if len(outcome) > 2 else (
            f"verified result for {mission_id}" if status == "completed" else ""
        )
        snapshot = MissionSnapshot(
            mission_id, self.missions[mission_id].goal, status, 1,
            summary, 0, 0, 1 if status == "completed" else 0, 0, 1,
        )
        self.missions[mission_id] = snapshot
        if should_stop:
            stop_event.set()
        return snapshot


class ProjectSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "missions.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def make_supervisor(self, engine):
        return ProjectSupervisor(
            engine, self.db, lease_seconds=10, heartbeat_seconds=0.1
        )

    def test_cli_accepts_existing_mission_adoption_for_project_supervisor(self):
        args = build_parser().parse_args([
            "--project-supervisor-run",
            "--task", "Finish and verify Streamiov.",
            "--project-supervisor-adopt-mission", "streamiov-platform",
            "--full-project-development",
        ])
        self.assertTrue(args.project_supervisor_run)
        self.assertEqual(args.project_supervisor_adopt_mission, "streamiov-platform")
        self.assertTrue(args.full_project_development)

    def test_project_completion_marker_stops_and_persists_supervisor(self):
        engine = FakeMissionEngine([
            ("completed", False),
            ("completed", True, "PROJECT_GOAL_COMPLETE: true All project objectives are verified."),
        ])
        supervisor = self.make_supervisor(engine)
        supervisor.configure("Complete every Streamiov objective.")
        result = supervisor.run(threading.Event(), poll_seconds=0.01, emit=lambda _message: None)

        self.assertEqual(result.status, "completed")
        self.assertTrue(supervisor.project_complete)
        self.assertEqual(len(engine.created), 2)
        self.assertEqual(len(engine.runs), 2)

        restarted = self.make_supervisor(engine)
        resumed = restarted.run(threading.Event(), poll_seconds=0.01, emit=lambda _message: None)
        self.assertEqual(resumed.mission_id, result.mission_id)
        self.assertEqual(len(engine.runs), 2)

    def test_existing_supervisor_database_migrates_project_status(self):
        with sqlite3.connect(self.db) as db:
            db.execute("""
                CREATE TABLE development_supervisors (
                    supervisor_key TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    active_mission_id TEXT,
                    progress TEXT NOT NULL DEFAULT '',
                    completed_missions INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    updated_at REAL NOT NULL
                )
            """)
            db.execute(
                "INSERT INTO development_supervisors(supervisor_key,goal,updated_at) VALUES(?,?,?)",
                ("streamiov-project", "Existing goal", 1.0),
            )
        supervisor = self.make_supervisor(FakeMissionEngine([]))
        self.assertFalse(supervisor.project_complete)
        with supervisor._connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(development_supervisors)")}
        self.assertIn("project_status", columns)

    def test_verified_mission_immediately_starts_next_distinct_mission(self):
        engine = FakeMissionEngine([("completed", False), ("completed", True)])
        supervisor = self.make_supervisor(engine)
        supervisor.configure("Finish the Streamiov platform safely.")
        events = []

        result = supervisor.run(threading.Event(), poll_seconds=0.01, emit=events.append)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(engine.created), 2)
        self.assertNotEqual(engine.created[0][0], engine.created[1][0])
        self.assertEqual(engine.runs, [engine.created[0][0], engine.created[1][0]])
        self.assertTrue(any(json.loads(event).get("event") == "supervisor_mission_verified" for event in events))

    def test_interrupted_mission_is_resumed_without_creating_duplicate(self):
        engine = FakeMissionEngine([("active", True), ("completed", True)])
        first = self.make_supervisor(engine)
        first.configure("Continue the Streamiov project.")
        first.run(threading.Event(), poll_seconds=0.01, emit=lambda _message: None)
        active_id = engine.created[0][0]

        second = self.make_supervisor(engine)
        second.run(threading.Event(), poll_seconds=0.01, emit=lambda _message: None)

        self.assertEqual(engine.created, [(active_id, engine.created[0][1])])
        self.assertEqual(engine.runs, [active_id, active_id])

    def test_configure_if_missing_preserves_restored_project_goal(self):
        engine = FakeMissionEngine([])
        supervisor = self.make_supervisor(engine)
        self.assertTrue(supervisor.configure_if_missing("Original durable goal."))
        self.assertFalse(supervisor.configure_if_missing("Changed context must not replace the goal."))
        with supervisor._connect() as db:
            row = db.execute(
                "SELECT goal FROM development_supervisors"
            ).fetchone()
        self.assertEqual(row["goal"], "Original durable goal.")

    def test_initialization_adopts_existing_platform_mission(self):
        engine = FakeMissionEngine([("completed", True)])
        mission_id = "streamiov-platform"
        engine.missions[mission_id] = MissionSnapshot(
            mission_id, "previous platform mission", "active", 4, "",
            1, 0, 2, 0, 3,
        )
        supervisor = self.make_supervisor(engine)
        self.assertTrue(supervisor.configure_if_missing(
            "Complete the full Streamiov platform.", active_mission_id=mission_id
        ))

        supervisor.run(threading.Event(), poll_seconds=0.01, emit=lambda _message: None)

        self.assertEqual(engine.runs, [mission_id])
        self.assertEqual(engine.created, [])

    def test_second_supervisor_cannot_take_live_lease(self):
        engine = FakeMissionEngine([])
        first = self.make_supervisor(engine)
        second = self.make_supervisor(engine)
        first.configure("One durable project goal.")
        first._acquire_lease()
        try:
            with self.assertRaises(ProjectSupervisorError):
                second._acquire_lease()
        finally:
            first._release_lease()

    def test_unverified_mission_does_not_advance_project(self):
        engine = FakeMissionEngine([("active", True)])
        supervisor = self.make_supervisor(engine)
        supervisor.configure("Do not skip verification.")
        supervisor.run(threading.Event(), poll_seconds=0.01, emit=lambda _message: None)

        with supervisor._connect() as db:
            row = db.execute(
                "SELECT active_mission_id,completed_missions FROM development_supervisors"
            ).fetchone()
        self.assertEqual(row["active_mission_id"], engine.created[0][0])
        self.assertEqual(row["completed_missions"], 0)
        self.assertEqual(len(engine.created), 1)


if __name__ == "__main__":
    unittest.main()
