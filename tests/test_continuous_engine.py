import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from ai.core.agent import AgentError
from ai.core.orchestrator import SpecialistTask
from ai.runtime.continuous_engine import (
    ContinuousDevelopmentEngine,
    MissionEngineError,
    MissionPlan,
    ModelMissionPlanner,
    _parse_planner_response,
)


class SequencePlanner:
    def __init__(self, plans):
        self.plans = list(plans)
        self.calls = []

    def plan(self, goal, progress, *, mission_id, cycle):
        self.calls.append((goal, progress, mission_id, cycle))
        if not self.plans:
            raise AssertionError("planner called more often than expected")
        return self.plans.pop(0)


class MissionEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "missions.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def make_engine(self, planner, agent_factory, **kwargs):
        return ContinuousDevelopmentEngine(
            self.db, planner, agent_factory, retry_base_seconds=0.01,
            lease_seconds=10, **kwargs,
        )

    def test_final_verification_requires_observed_successful_test_evidence(self):
        engine = self.make_engine(SequencePlanner([]), lambda role: None)
        mission_id = engine.create_mission("Verify with real command output.")
        payloads = {
            "missing": {"passed": True, "findings": []},
            "failed": {
                "passed": True, "findings": [],
                "tool_evidence": [{"tool": "run_tests", "result": "exit_code=1\nFAILED"}],
            },
            "misleading": {
                "passed": True, "findings": [],
                "tool_evidence": [{"tool": "run_tests", "result": "exit_code=1\nFAILED; expected exit_code=0"}],
            },
            "interrupted": {
                "passed": False,
                "findings": ["Final verification test command failed; observed output: exit_code=-15"],
                "tool_evidence": [{"tool": "run_tests", "result": "exit_code=-15\n"}],
            },
            "observed": {
                "passed": True, "findings": [],
                "tool_evidence": [{"tool": "run_tests", "result": "exit_code=0\nOK"}],
            },
            "non_empty_findings": {
                "passed": True, "findings": ["No tests observed."],
                "tool_evidence": [{"tool": "run_tests", "result": "exit_code=0\nOK"}],
            },
            "benign_findings": {
                "passed": True, "findings": ["no errors detected"],
                "tool_evidence": [{"tool": "run_tests", "result": "exit_code=0\nOK"}],
            },
        }
        for index, (label, payload) in enumerate(payloads.items()):
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("""
                    INSERT INTO development_mission_tasks
                    (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                     result,available_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    f"{mission_id}:1:verify-{label}", mission_id, 1, "testing",
                    "STREAMIOV_FINAL_VERIFICATION: inspect", "[]", "succeeded", 1,
                    json.dumps(payload), time.time(), time.time(), time.time() + index,
                ))
            verification = engine._latest_final_verification(mission_id, 1)
            if label == "observed":
                self.assertIs(verification["passed"], True)
                self.assertNotIn("invalid", verification)
            else:
                self.assertIs(verification["passed"], False)
                self.assertTrue(verification["invalid"])
                if label == "interrupted":
                    self.assertIn("interrupted", verification["findings"][0])
                    plan = engine._require_final_verification(mission_id, 1, "Verify with real command output.")
                    self.assertEqual(plan.tasks[0].task_id, "mandatory-final-verification")

    def test_final_verification_accepts_only_successful_game_checks_evidence(self):
        engine = self.make_engine(SequencePlanner([]), lambda role: None)
        mission_id = engine.create_mission("Verify a game.")
        reports = {
            "passed": {
                "passed": True, "findings": [],
                "tool_evidence": [{"tool": "run_game_checks", "result": "exit_code=0\naudit ok"}],
            },
            "failed": {
                "passed": True, "findings": [],
                "tool_evidence": [{"tool": "run_game_checks", "result": "exit_code=1\nfailed"}],
            },
        }
        for index, (label, report) in enumerate(reports.items()):
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("""
                    INSERT INTO development_mission_tasks
                    (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                     result,available_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    f"{mission_id}:1:game-{label}", mission_id, 1, "testing",
                    "STREAMIOV_FINAL_VERIFICATION: inspect", "[]", "succeeded", 1,
                    json.dumps(report), time.time(), time.time(), time.time() + index,
                ))
            verification = engine._latest_final_verification(mission_id, 1)
            if label == "passed":
                self.assertIs(verification["passed"], True)
                self.assertNotIn("invalid", verification)
            else:
                self.assertIs(verification["passed"], False)
                self.assertTrue(verification["invalid"])

    def test_repair_task_prompt_does_not_enter_read_only_verification_mode(self):
        engine = self.make_engine(SequencePlanner([]), lambda role: None)
        mission_id = engine.create_mission("Repair a verified failure.")
        report = {
            "passed": False,
            "findings": ["fix failing assertion"],
            "tool_evidence": [{"tool": "run_tests", "result": "exit_code=1\nFAILED"}],
        }
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,available_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"{mission_id}:1:verify", mission_id, 1, "testing",
                "STREAMIOV_FINAL_VERIFICATION: inspect", "[]", "succeeded", 1,
                json.dumps(report), time.time(), time.time(), time.time(),
            ))
        plan = engine._require_final_verification(mission_id, 2, "Repair a verified failure.")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.tasks[0].specialist, "ai_repair_agent")
        self.assertIn("STREAMIOV_VERIFICATION_REPAIR", plan.tasks[0].prompt)
        self.assertNotIn("STREAMIOV_FINAL_VERIFICATION", plan.tasks[0].prompt)
        self.assertIn("fix failing assertion", plan.tasks[0].prompt)

    def test_failed_verification_repair_is_retried_before_new_verification(self):
        engine = self.make_engine(SequencePlanner([]), lambda role: None)
        mission_id = engine.create_mission("Retry a failed verification repair.")
        report = {
            "passed": False,
            "findings": ["fix failing assertion"],
            "tool_evidence": [{"tool": "run_tests", "result": "exit_code=1\nFAILED"}],
        }
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,available_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"{mission_id}:1:verify", mission_id, 1, "testing",
                "STREAMIOV_FINAL_VERIFICATION: inspect", "[]", "succeeded", 1,
                json.dumps(report), time.time(), time.time(), time.time(),
            ))
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 last_error,available_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"{mission_id}:2:repair", mission_id, 2, "ai_repair_agent",
                "STREAMIOV_VERIFICATION_REPAIR: repair", "[]", "failed", 1,
                "AgentError: Model action protocol remained invalid after 3 bounded corrections; refusing to execute.",
                time.time(), time.time(), time.time() + 1,
            ))
        plan = engine._require_final_verification(mission_id, 3, "Retry a failed verification repair.")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.tasks[0].specialist, "ai_repair_agent")
        self.assertIn("retry-verification-repair", plan.tasks[0].task_id)
        self.assertIn("STREAMIOV_VERIFICATION_REPAIR", plan.tasks[0].prompt)
        self.assertNotIn("STREAMIOV_FINAL_VERIFICATION", plan.tasks[0].prompt)
        self.assertIn("fix failing assertion", plan.tasks[0].prompt)
        self.assertIn("Model action protocol remained invalid", plan.tasks[0].prompt)

    def test_successful_verification_repair_returns_to_independent_verification(self):
        engine = self.make_engine(SequencePlanner([]), lambda role: None)
        mission_id = engine.create_mission("Verify after a completed repair.")
        report = {
            "passed": False,
            "findings": ["fix failing assertion"],
            "tool_evidence": [{"tool": "run_tests", "result": "exit_code=1\nFAILED"}],
        }
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,available_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"{mission_id}:1:verify", mission_id, 1, "testing",
                "STREAMIOV_FINAL_VERIFICATION: inspect", "[]", "succeeded", 1,
                json.dumps(report), time.time(), time.time(), time.time(),
            ))
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,available_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"{mission_id}:2:repair", mission_id, 2, "ai_repair_agent",
                "STREAMIOV_VERIFICATION_REPAIR: repair", "[]", "succeeded", 1,
                "Repaired.", time.time(), time.time(), time.time() + 1,
            ))
        plan = engine._require_final_verification(mission_id, 3, "Verify after a completed repair.")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.tasks[0].specialist, "ai_testing_agent")
        self.assertIn("mandatory-final-verification", plan.tasks[0].task_id)
        self.assertIn("STREAMIOV_FINAL_VERIFICATION", plan.tasks[0].prompt)
        self.assertIn("fix failing assertion", plan.tasks[0].prompt)
        self.assertIn('"passed":true,"findings":[]', plan.tasks[0].prompt)
        self.assertIn("verification must be run again", plan.tasks[0].prompt)
        self.assertIn("Independently inspect", plan.tasks[0].prompt)

    def test_successful_verification_supersedes_pending_repair_tasks(self):
        engine = self.make_engine(SequencePlanner([]), lambda role: None)
        mission_id = engine.create_mission("Finish without stale repair work.")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,available_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"{mission_id}:1:verify", mission_id, 1, "testing",
                "STREAMIOV_FINAL_VERIFICATION: inspect", "[]", "succeeded", 1,
                json.dumps({
                    "passed": True, "findings": [],
                    "tool_evidence": [{"tool": "run_tests", "result": "exit_code=0\nOK"}],
                }),
                time.time(), time.time(), time.time(),
            ))
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 available_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f"{mission_id}:2:repair", mission_id, 2, "ai_repair_agent",
                "STREAMIOV_VERIFICATION_REPAIR: repair", "[]", "queued", 0,
                time.time(), time.time(), time.time(),
            ))
        self.assertIsNone(engine._require_final_verification(mission_id, 3, "Finish without stale repair work."))
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT status,last_error_class FROM development_mission_tasks WHERE task_id=?",
                (f"{mission_id}:2:repair",),
            ).fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["last_error_class"], "superseded")

    def test_progress_context_stays_within_provider_budget_and_keeps_latest_outcomes(self):
        engine = self.make_engine(SequencePlanner([]), lambda _role: None)
        mission_id = engine.create_mission("Keep planning requests bounded")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute(
                "UPDATE development_missions SET summary=? WHERE mission_id=?",
                ("S" * 10_000, mission_id),
            )
            for index in range(30):
                db.execute(
                    """
                    INSERT INTO development_mission_tasks
                    (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                     result,last_error,available_at,worker_id,lease_until,created_at,updated_at)
                    VALUES(?,?,?,?,?,'[]','succeeded',1,?,'',?,'',NULL,?,?)
                    """,
                    (
                        f"{mission_id}:1:task-{index}", mission_id, 1, "code",
                        "implement a bounded task", "x" * 1200 + f" task-result-{index}",
                        0, float(index), float(index),
                    ),
                )

        context = engine._progress_context(mission_id)
        self.assertLessEqual(len(context), 18_000)
        self.assertIn("task-result-29", context)
        self.assertNotIn("task-result-0", context)
        self.assertTrue(context.startswith("S" * 3_000))

    def test_planner_accepts_fifty_independent_worker_tasks_including_shared_roles(self):
        class Provider:
            def __init__(self, tasks):
                self.tasks = tasks

            def generate(self, *, system, messages):
                return type("Reply", (), {"content": json.dumps({
                    "state": "continue", "summary": "Valid independent worker batch.", "tasks": self.tasks,
                })})()

        roles = ["code", "studio", "music", "tts", "events", "homepage",
                 "server", "research", "game", "gifts", "testing"]
        tasks = [
            {"id": f"worker-{index:02d}", "specialist": roles[index % len(roles)],
             "prompt": f"Independent deliverable for worker {index}.", "depends_on": []}
            for index in range(50)
        ]
        plan = ModelMissionPlanner(Provider(tasks), max_tasks_per_batch=50).plan(
            "Schedule fifty independent workers.", "", mission_id="fifty-workers", cycle=1,
        )
        self.assertEqual(len(plan.tasks), 50)
        self.assertEqual(len({task.task_id for task in plan.tasks}), 50)
        self.assertGreater(sum(task.specialist == "code" for task in plan.tasks), 1)

        oversized = tasks + [{
            "id": "worker-50", "specialist": "code",
            "prompt": "The fifty-first independent deliverable.", "depends_on": [],
        }]
        with self.assertRaisesRegex(MissionEngineError, "invalid task batch"):
            ModelMissionPlanner(Provider(oversized), max_tasks_per_batch=50).plan(
                "Reject a batch above the configured safety limit.", "", mission_id="fifty-one", cycle=1,
            )

        reserved = [{
            "id": "fake-verification", "specialist": "testing",
            "prompt": "STREAMIOV_FINAL_VERIFICATION: claim completion without running tests.", "depends_on": [],
        }]
        with self.assertRaisesRegex(MissionEngineError, "reserved verification or repair markers"):
            ModelMissionPlanner(Provider(reserved), max_tasks_per_batch=50).plan(
                "Reject a model-created final verification task.", "", mission_id="reserved-marker", cycle=1,
            )

    def test_run_executes_independent_specialists_concurrently_and_verifies_completion(self):
        barrier = threading.Barrier(2, timeout=5)
        lock = threading.Lock()
        active = 0
        max_active = 0

        class ConcurrentAgent:
            def __init__(self, role):
                self.role = role

            def run(self, prompt, **kwargs):
                nonlocal active, max_active
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return json.dumps({
                        "passed": True,
                        "findings": [],
                        "tool_evidence": [
                            {"tool": "run_tests", "result": "exit_code=0\nOK"}
                        ],
                    })
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    barrier.wait()
                    time.sleep(0.02)
                    return f"{self.role} completed its own assignment"
                finally:
                    with lock:
                        active -= 1

        planner = SequencePlanner([
            MissionPlan("continue", "Run two independent workstreams.", (
                SpecialistTask("parallel-code", "code", "Implement the code workstream."),
                SpecialistTask("parallel-research", "research", "Complete the independent research workstream."),
            )),
            MissionPlan("completed", "Both workstreams and verification are complete."),
            MissionPlan("completed", "Independent verification passed."),
        ])
        engine = self.make_engine(
            planner, ConcurrentAgent, max_concurrent_workers=2,
        )
        mission_id = engine.create_mission("Verify real parallel specialist execution")
        snapshot = engine.run(mission_id, threading.Event(), poll_seconds=0.01)
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.completed_tasks, 3)
        self.assertEqual(max_active, 2)

    def test_repeated_task_failures_never_create_a_terminal_mission_stop(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Recover the task.", (
                SpecialistTask("retry", "code", "retry this task using a different strategy"),
            )),
        ])
        engine = ContinuousDevelopmentEngine(
            self.db, planner, lambda _role: None, retry_base_seconds=0.01,
            lease_seconds=10, max_task_failures=3,
        )
        mission_id = engine.create_mission("Keep a specialist task resumable")
        engine._claim_planning(mission_id, "planner")
        engine._store_plan(mission_id, "planner", 1, planner.plans[0])

        for failure in range(1, 7):
            task = engine._claim_task(mission_id, "worker")
            self.assertIsNotNone(task)
            self.assertEqual(task.attempts, failure)
            outcome = engine._finish_task(task.task_id, "worker", error=f"RuntimeError: failure {failure}")
            self.assertEqual(outcome, "queued")
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute(
                    "UPDATE development_mission_tasks SET available_at=0 WHERE task_id=?",
                    (task.task_id,),
                )

        snapshot = engine.get_mission(mission_id)
        self.assertEqual(snapshot.pending_tasks, 1)
        self.assertEqual(snapshot.failed_tasks, 0)
        self.assertEqual(snapshot.attempts, 6)
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute(
                "SELECT status,failure_count,last_error FROM development_mission_tasks WHERE task_id=?",
                (f"{mission_id}:1:retry",),
            ).fetchone()
        self.assertEqual(row, ("queued", 6, "RuntimeError: failure 6"))

    def test_repeated_invalid_action_protocol_is_blocked_across_engine_slices(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Run one protocol task and one independent task.", (
                SpecialistTask("a-protocol", "code", "produce valid tool actions"),
                SpecialistTask("z-independent", "research", "continue independent research"),
            )),
        ])
        engine = self.make_engine(planner, lambda _role: None, max_task_failures=3)
        mission_id = engine.create_mission("Bound repeated invalid specialist action responses")
        engine._claim_planning(mission_id, "planner")
        engine._store_plan(mission_id, "planner", 1, planner.plans[0])
        repeated_error = (
            "AgentError: Model action protocol remained invalid after 3 bounded corrections; "
            "refusing to execute."
        )

        for attempt in range(1, 4):
            task = engine._claim_task(mission_id, "worker")
            self.assertIsNotNone(task)
            self.assertTrue(task.task_id.endswith(":a-protocol"))
            outcome = engine._finish_task(task.task_id, "worker", error=repeated_error)
            self.assertEqual(outcome, "failed" if attempt == 3 else "queued")
            if attempt < 3:
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute(
                        "UPDATE development_mission_tasks SET available_at=0 WHERE task_id=?",
                        (task.task_id,),
                    )

        blocked = engine.get_mission(mission_id)
        self.assertEqual(blocked.failed_tasks, 1)
        self.assertEqual(blocked.pending_tasks, 1)
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute(
                "SELECT status,failure_count,last_error_class,last_error FROM development_mission_tasks WHERE task_id=?",
                (f"{mission_id}:1:a-protocol",),
            ).fetchone()
        self.assertEqual(row[0:3], ("failed", 3, "action_protocol"))
        self.assertIn("refusing to execute", row[3])

        # A separate specialist remains eligible even though the protocol task is blocked.
        independent = engine._claim_task(mission_id, "worker")
        self.assertIsNotNone(independent)
        self.assertTrue(independent.task_id.endswith(":z-independent"))
        self.assertEqual(engine._finish_task(independent.task_id, "worker", result="research complete"), "succeeded")

        resumed_engine = self.make_engine(planner, lambda _role: None, max_task_failures=3)
        resumed = resumed_engine.get_mission(mission_id)
        self.assertEqual(resumed.failed_tasks, 1)
        self.assertIsNone(resumed_engine._claim_task(mission_id, "next-slice"))

    def test_terminal_action_protocol_stops_the_slice_before_replanning(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Run one protocol task.", (
                SpecialistTask("protocol", "code", "produce valid tool actions"),
            )),
        ])

        class InvalidActionAgent:
            def run(self, prompt, *, checkpoint_id=None, cancel_event=None):
                raise AgentError(
                    "Model action protocol remained invalid after 3 bounded corrections; refusing to execute."
                )

        engine = self.make_engine(planner, lambda _role: InvalidActionAgent(), max_task_failures=3)
        mission_id = engine.create_mission("Stop invalid protocol loops before the runner deadline")
        stop_event = threading.Event()
        events = []
        snapshot = engine.run(mission_id, stop_event, poll_seconds=0.01, emit=events.append)
        self.assertTrue(stop_event.is_set())
        self.assertEqual(len(planner.calls), 1)
        self.assertGreaterEqual(snapshot.failed_tasks, 1)
        self.assertTrue(any(
            json.loads(item).get("event") == "mission_protocol_blocked" for item in events
        ))
        self.assertIn(mission_id, engine._protocol_blocked_missions)
        self.assertEqual(engine.get_mission(mission_id).status, "active")

    def test_worker_timeout_backoff_is_classified_and_persisted_across_slices(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Wait safely after provider timeout.", (
                SpecialistTask("timeout", "code", "call the configured provider"),
            )),
        ])
        engine = self.make_engine(planner, lambda _role: None)
        mission_id = engine.create_mission("Persist provider timeout backoff")
        engine._claim_planning(mission_id, "planner")
        engine._store_plan(mission_id, "planner", 1, planner.plans[0])
        timeout_error = "TimeoutError: Cloudflare Worker request timed out"

        first = engine._claim_task(mission_id, "worker")
        before = time.time()
        self.assertEqual(engine._finish_task(first.task_id, "worker", error=timeout_error), "queued")
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute(
                "SELECT failure_count,last_error_class,available_at FROM development_mission_tasks WHERE task_id=?",
                (first.task_id,),
            ).fetchone()
        self.assertEqual(row[0:2], (1, "provider_timeout"))
        self.assertGreaterEqual(row[2] - before, 60)

        resumed_engine = self.make_engine(planner, lambda _role: None)
        self.assertIsNone(resumed_engine._claim_task(mission_id, "next-slice"))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute(
                "UPDATE development_mission_tasks SET available_at=0 WHERE task_id=?",
                (first.task_id,),
            )
        second = resumed_engine._claim_task(mission_id, "next-slice")
        self.assertIsNotNone(second)
        before_second = time.time()
        self.assertEqual(resumed_engine._finish_task(second.task_id, "next-slice", error=timeout_error), "queued")
        with closing(sqlite3.connect(self.db)) as db, db:
            second_available = db.execute(
                "SELECT available_at FROM development_mission_tasks WHERE task_id=?",
                (first.task_id,),
            ).fetchone()[0]
        self.assertGreaterEqual(second_available - before_second, 120)

    def test_planner_response_parser_accepts_markdown_json_fences_and_preambles(self):
        responses = (
            ' ```json\n{"state":"completed","summary":"Verified.","tasks":[]}\n``` ',
            'Here is the requested plan:\n```json\n{"state":"completed","summary":"Verified.","tasks":[]}\n```',
        )
        for response in responses:
            with self.subTest(response=response[:20]):
                payload = _parse_planner_response(response)
                self.assertEqual(payload["state"], "completed")
                self.assertEqual(payload["summary"], "Verified.")

    def test_planner_retries_one_malformed_response_with_a_format_correction(self):
        class Provider:
            def __init__(self):
                self.responses = [
                    "I will now provide the plan, but forgot the JSON object.",
                    type("Reply", (), {
                        "content": json.dumps({
                            "state": "completed",
                            "summary": "The task is already complete.",
                            "tasks": [],
                        })
                    })(),
                ]
                self.calls = []

            def generate(self, *, system, messages):
                self.calls.append(messages)
                value = self.responses.pop(0)
                return type("Reply", (), {"content": value})() if isinstance(value, str) else value

        provider = Provider()
        plan = ModelMissionPlanner(provider).plan(
            "Verify a completed task.", "", mission_id="format-retry", cycle=1,
        )
        self.assertEqual(plan.state, "completed")
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("FORMAT CORRECTION", provider.calls[1][-1]["content"])

    def test_planner_retries_dependency_schema_errors_twice_before_accepting_a_valid_plan(self):
        class Provider:
            def __init__(self):
                self.responses = [
                    json.dumps({"state": "continue", "summary": "Bad dependency shape.", "tasks": [
                        {"id": "base", "specialist": "code", "prompt": "Build base.", "depends_on": ["missing"]}
                    ]}),
                    json.dumps({"state": "continue", "summary": "Still invalid.", "tasks": [
                        {"id": "base", "specialist": "code", "prompt": "Build base.", "depends_on": ["not-in-batch"]}
                    ]}),
                    json.dumps({"state": "continue", "summary": "Valid repaired plan.", "tasks": [
                        {"id": "base", "specialist": "code", "prompt": "Build base.", "depends_on": []}
                    ]}),
                ]
                self.calls = []

            def generate(self, *, system, messages):
                self.calls.append(messages)
                return type("Reply", (), {"content": self.responses.pop(0)})()

        provider = Provider()
        plan = ModelMissionPlanner(provider).plan(
            "Repair invalid task dependencies.", "", mission_id="dependency-retry", cycle=2,
        )
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].depends_on, ())
        self.assertEqual(len(provider.calls), 3)
        self.assertIn("depends_on MUST be a JSON array of strings", provider.calls[2][-1]["content"])
        self.assertIn("Multiple independent workers may share a specialist role", provider.calls[2][-1]["content"])
        self.assertIn("never collapse separate assignments into one task", provider.calls[2][-1]["content"])

    def test_existing_mission_database_is_migrated_with_retry_columns(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript("""
                CREATE TABLE development_missions (
                    mission_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','completed')),
                    cycle INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    planning_owner TEXT NOT NULL DEFAULT '',
                    planning_lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE development_mission_tasks (
                    task_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES development_missions(mission_id),
                    cycle INTEGER NOT NULL,
                    specialist TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    available_at REAL NOT NULL,
                    worker_id TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                INSERT INTO development_missions
                (mission_id,goal,status,created_at,updated_at)
                VALUES('legacy-mission','Preserve old task','active',1,1);
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,last_error,available_at,worker_id,lease_until,created_at,updated_at)
                VALUES('legacy-task','legacy-mission',1,'code','legacy prompt','[]',
                       'queued',2,'partial result','',0,'',NULL,1,1);
            """)

        engine = self.make_engine(SequencePlanner([]), lambda _role: None)
        mission_id = engine.create_mission("Upgrade an existing durable mission")
        with closing(sqlite3.connect(self.db)) as db, db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(development_missions)")}
            task_columns = {row[1] for row in db.execute("PRAGMA table_info(development_mission_tasks)")}
            row = db.execute(
                "SELECT planning_failures,planning_retry_at FROM development_missions WHERE mission_id=?",
                (mission_id,),
            ).fetchone()
            legacy = db.execute(
                "SELECT status,attempts,failure_count,result FROM development_mission_tasks WHERE task_id='legacy-task'"
            ).fetchone()
            db.execute("UPDATE development_mission_tasks SET status='failed' WHERE task_id='legacy-task'")
            migrated_status = db.execute(
                "SELECT status FROM development_mission_tasks WHERE task_id='legacy-task'"
            ).fetchone()[0]
        self.assertIn("planning_failures", columns)
        self.assertIn("planning_retry_at", columns)
        self.assertIn("failure_count", task_columns)
        self.assertEqual(row, (0, None))
        self.assertEqual(legacy, ("queued", 2, 0, "partial result"))
        self.assertEqual(migrated_status, "failed")


    def test_daily_ai_quota_exhaustion_uses_long_backoff_without_stalling_other_work(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Wait for the free AI quota to reset.", (
                SpecialistTask("quota-task", "code", "resume after quota reset"),
            )),
            MissionPlan("continue", "Use an independently executable recovery task.", (
                SpecialistTask("recovery-task", "research", "inspect current state with local recovery"),
            )),
        ])

        class LocalAgent:
            def run(self, prompt, **_kwargs):
                return "local recovery observed"

        stop_event = threading.Event()
        events = []

        def emit(message):
            events.append(message)
            if '"event": "task_succeeded"' in message:
                stop_event.set()

        engine = self.make_engine(planner, lambda _role: LocalAgent())
        mission_id = engine.create_mission("Continue useful work after daily AI quota exhaustion")
        engine._claim_planning(mission_id, "planner")
        engine._store_plan(mission_id, "planner", 1, planner.plans.pop(0))
        task = engine._claim_task(mission_id, "worker")
        self.assertIsNotNone(task)

        before = time.time()
        engine._finish_task(
            task.task_id, "worker",
            error="CloudflareWorkerError: HTTP 429 (code: daily_ai_limit_reached)",
        )
        with closing(sqlite3.connect(self.db)) as db, db:
            available_at = db.execute(
                "SELECT available_at FROM development_mission_tasks WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]
        self.assertGreaterEqual(available_at - before, 6 * 60 * 60 - 1)

        snapshot = engine.run(
            mission_id, stop_event, poll_seconds=0.01, emit=emit,
        )
        self.assertEqual(snapshot.status, "active")
        self.assertEqual(len(planner.calls), 1)
        self.assertTrue(any('"event": "mission_waiting_for_retry"' in event for event in events))
        self.assertTrue(any('"event": "task_succeeded"' in event for event in events))
        with closing(sqlite3.connect(self.db)) as db, db:
            states = dict(db.execute(
                "SELECT task_id,status FROM development_mission_tasks WHERE mission_id=?",
                (mission_id,),
            ).fetchall())
        self.assertEqual(states[f"{mission_id}:2:recovery-task"], "succeeded")


    def test_daily_ai_quota_exhaustion_pauses_planner_and_returns_runner_slice(self):
        class QuotaPlanner:
            def plan(self, goal, progress, *, mission_id, cycle):
                raise RuntimeError("CloudflareWorkerError: HTTP 429 (code: daily_ai_limit_reached)")

        engine = self.make_engine(QuotaPlanner(), lambda _role: None)
        mission_id = engine.create_mission("Pause planner until free AI quota resets")
        events = []
        before = time.time()
        snapshot = engine.run(
            mission_id, threading.Event(), poll_seconds=0.01, emit=events.append,
        )
        with closing(sqlite3.connect(self.db)) as db, db:
            retry_at = db.execute(
                "SELECT planning_retry_at FROM development_missions WHERE mission_id=?",
                (mission_id,),
            ).fetchone()[0]
        self.assertEqual(snapshot.status, "active")
        self.assertEqual(snapshot.cycle, 0)
        self.assertGreaterEqual(retry_at - before, 6 * 60 * 60 - 1)
        self.assertTrue(any('"event": "planning_retry_scheduled"' in event for event in events))
        self.assertTrue(any('"event": "mission_waiting_for_planning_retry"' in event for event in events))

    def test_dependency_blocked_queued_task_is_failed_and_replanning_continues(self):
        engine = self.make_engine(SequencePlanner([]), lambda _role: None)
        mission_id = engine.create_mission("Recover from an impossible dependency")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,last_error,available_at,worker_id,lease_until,created_at,updated_at)
                VALUES(?,?,?,?,?,?,'queued',1,'','',0,'',NULL,1,1)
            """, (
                f"{mission_id}:1:blocked-task", mission_id, 1, "code",
                "Blocked task", json.dumps(["missing-prerequisite"]),
            ))

        claim = engine._claim_planning(mission_id, "planner")
        self.assertIsNotNone(claim)
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute(
                "SELECT status,last_error_class,last_error FROM development_mission_tasks WHERE task_id=?",
                (f"{mission_id}:1:blocked-task",),
            ).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(row[1], "dependency_blocked")
        self.assertIn("missing-prerequisite", row[2])

    def test_dependency_deferred_task_does_not_stop_new_planning(self):
        engine = self.make_engine(SequencePlanner([]), lambda _role: None)
        mission_id = engine.create_mission("Plan while a verification task waits")
        future = time.time() + 6 * 60 * 60
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executemany("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,last_error,available_at,worker_id,lease_until,created_at,updated_at)
                VALUES(?,?,?,?,?,?,'queued',1,'','',?,'',NULL,1,1)
            """, [
                (
                    f"{mission_id}:1:repair", mission_id, 1, "ai_repair_agent",
                    "Repair", "[]", future,
                ),
                (
                    f"{mission_id}:1:verify", mission_id, 1, "ai_testing_agent",
                    "Verify", json.dumps(["repair"]), 0,
                ),
            ])

        claim = engine._claim_planning(mission_id, "planner")
        self.assertIsNotNone(claim)
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute(
                "SELECT status,last_error_class FROM development_mission_tasks WHERE task_id=?",
                (f"{mission_id}:1:verify",),
            ).fetchone()
        self.assertEqual(row[0], "queued")
        self.assertEqual(row[1], "")

    def test_replanning_stops_before_unbounded_backlogged_task_creation(self):
        engine = self.make_engine(SequencePlanner([]), lambda _role: None)
        mission_id = engine.create_mission("Bound blocked recovery planning")
        future = time.time() + 6 * 60 * 60
        with closing(sqlite3.connect(self.db)) as db, db:
            for index in range(3):
                db.execute("""
                    INSERT INTO development_mission_tasks
                    (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                     result,last_error,available_at,worker_id,lease_until,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,'queued',1,'','',?,'',NULL,1,1)
                """, (
                    f"{mission_id}:1:blocked-{index}", mission_id, 1, "code",
                    "Backed off task", "[]", future,
                ))
        self.assertIsNone(engine._claim_planning(mission_id, "planner"))

    def test_planning_retry_backoff_survives_engine_recreation(self):
        engine = self.make_engine(SequencePlanner([]), lambda _role: None)
        mission_id = engine.create_mission("Persist planner backoff")
        self.assertIsNotNone(engine._claim_planning(mission_id, "first-worker"))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute(
                "UPDATE development_missions SET planning_owner='',planning_lease_until=NULL,"
                "planning_failures=4,planning_retry_at=? WHERE mission_id=?",
                (time.time() + 60, mission_id),
            )

        resumed = self.make_engine(SequencePlanner([]), lambda _role: None)
        self.assertIsNone(resumed._claim_planning(mission_id, "second-worker"))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute(
                "UPDATE development_missions SET planning_retry_at=0 WHERE mission_id=?",
                (mission_id,),
            )
        self.assertIsNotNone(resumed._claim_planning(mission_id, "second-worker"))

    def test_model_planner_assigns_distinct_work_to_all_eleven_specialists(self):
        roles = ["code", "studio", "music", "tts", "events", "homepage", "server", "research", "game", "gifts", "testing"]

        class Provider:
            def __init__(self, tasks):
                self.tasks = tasks

            def generate(self, *, system, messages):
                self.system = system
                return type("Reply", (), {
                    "content": json.dumps({
                        "state": "continue",
                        "summary": "Eleven independent workstreams.",
                        "tasks": self.tasks,
                    })
                })()

        distinct_tasks = [
            {"id": role, "specialist": role, "prompt": f"Deliver the {role} workstream.", "depends_on": []}
            for role in roles
        ]
        provider = Provider(distinct_tasks)
        plan = ModelMissionPlanner(provider).plan(
            "Build the complete Streamiov platform.", "No work completed yet.",
            mission_id="eleven-specialists", cycle=1,
        )
        self.assertEqual([task.specialist for task in plan.tasks], roles)
        self.assertIn("1–50 independent tasks", provider.system)
        self.assertEqual(len({task.prompt for task in plan.tasks}), 11)

        duplicate_aliases = [
            {"id": "legacy-core", "specialist": "core", "prompt": "Research the model runtime.", "depends_on": []},
            {"id": "research", "specialist": "research", "prompt": "Build the model runtime.", "depends_on": []},
        ]
        duplicate_role_plan = ModelMissionPlanner(Provider(duplicate_aliases)).plan(
            "Build AI infrastructure with two independent research workers.", "",
            mission_id="duplicate-specialist", cycle=1,
        )
        self.assertEqual(len(duplicate_role_plan.tasks), 2)
        self.assertEqual([task.specialist for task in duplicate_role_plan.tasks], ["core", "research"])

    def test_mission_continues_across_unbounded_planning_cycles_until_explicit_completion(self):
        planner = SequencePlanner([
            MissionPlan("continue", "First phase recorded.", (
                SpecialistTask("foundation", "core", "build foundation"),
            )),
            MissionPlan("continue", "Second phase recorded.", (
                SpecialistTask("followup", "code", "record followup work"),
            )),
            MissionPlan("completed", "Planner confirms all objectives."),
            MissionPlan("completed", "Final independent verification passed."),
        ])
        calls = []

        class Agent:
            def __init__(self, role):
                self.role = role

            def run(self, prompt):
                calls.append((self.role, prompt))
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return '{"passed":true,"findings":[],"tool_evidence":[{"tool":"run_tests","result":"exit_code=0\\nOK"}]}'
                return f"verified: {prompt}"

        engine = self.make_engine(planner, lambda role: Agent(role))
        mission_id = engine.create_mission("Complete the platform")
        events = []
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=events.append)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.cycle, 3)
        self.assertEqual(result.completed_tasks, 3)
        self.assertEqual([item[0] for item in calls], ["core", "code", "ai_testing_agent"])
        self.assertEqual(len(planner.calls), 4)
        saved_plans = [json.loads(event) for event in events if '"event": "plan_saved"' in event]
        enforced_verification = next(item for item in saved_plans if item["cycle"] == 3)
        self.assertEqual(enforced_verification["state"], "continue")
        self.assertEqual(enforced_verification["task_count"], 1)

    def test_verification_no_tool_failure_is_bounded_and_does_not_complete_mission(self):
        planner = SequencePlanner([MissionPlan("completed", "Ready.")])
        stop = threading.Event()
        events = []

        class NoToolAgent:
            def run(self, _prompt):
                raise AgentError(
                    "Refusing to report task success without at least one successfully executed project tool."
                )

        def emit(message):
            events.append(message)
            try:
                event = json.loads(message)
            except (TypeError, json.JSONDecodeError):
                return
            if event.get("event") == "task_blocked":
                stop.set()

        engine = ContinuousDevelopmentEngine(
            self.db, planner, lambda _role: NoToolAgent(),
            retry_base_seconds=0.01, lease_seconds=10, max_task_failures=3,
        )
        mission_id = engine.create_mission("Verify a bounded verifier failure.")
        result = engine.run(mission_id, stop, poll_seconds=0.01, emit=emit)

        self.assertEqual(result.status, "active")
        blocked = [json.loads(item) for item in events if '"event": "task_blocked"' in item]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["error_class"], "verification_no_tool")
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute(
                "SELECT status,failure_count,last_error_class FROM development_mission_tasks "
                "WHERE prompt LIKE '%STREAMIOV_FINAL_VERIFICATION%'"
            ).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(row[1], 3)
        self.assertEqual(row[2], "verification_no_tool")

    def test_agent_interruption_is_persisted_and_mission_can_be_stopped_safely(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Implement a component.", (
                SpecialistTask("component", "code", "implement component"),
            )),
        ])
        events = []
        stop = threading.Event()

        class BrokenAgent:
            def run(self, _prompt):
                stop.set()
                raise RuntimeError("persistent invalid action protocol")

        engine = ContinuousDevelopmentEngine(
            self.db, planner, lambda _role: BrokenAgent(),
            retry_base_seconds=0.01, lease_seconds=10, max_task_failures=1,
        )
        mission_id = engine.create_mission("Persist failure and remain resumable")
        result = engine.run(mission_id, stop, poll_seconds=0.01, emit=events.append)

        self.assertEqual(result.status, "active")
        self.assertEqual(result.failed_tasks, 0)
        self.assertEqual(result.pending_tasks, 1)
        self.assertEqual(result.completed_tasks, 0)
        self.assertEqual(len(planner.calls), 1)
        self.assertTrue(any('"event": "task_interrupted"' in event for event in events))
        self.assertFalse(any('"event": "mission_blocked"' in event for event in events))
        self.assertFalse(any('"event": "mission_completed"' in event for event in events))

    def test_transient_task_failures_retry_and_recover_before_the_failure_limit(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Implement a component.", (
                SpecialistTask("component", "code", "implement component"),
            )),
            MissionPlan("completed", "Planner confirms component work."),
            MissionPlan("completed", "Final independent verification passed."),
        ])
        attempts = []

        class Agent:
            def run(self, prompt):
                attempts.append(prompt)
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return '{"passed":true,"findings":[],"tool_evidence":[{"tool":"run_tests","result":"exit_code=0\\nOK"}]}'
                if len(attempts) < 3:
                    raise RuntimeError("transient model/tool failure")
                return "component implemented and tested"

        engine = self.make_engine(planner, lambda _role: Agent())
        mission_id = engine.create_mission("Implement component")
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.attempts, 4)
        self.assertIn("transient model/tool failure", attempts[1])
        self.assertIn("transient model/tool failure", attempts[2])

    def test_mission_state_survives_engine_recreation(self):
        planner = SequencePlanner([
            MissionPlan("continue", "First work unit.", (
                SpecialistTask("persist", "core", "persist this work"),
            )),
            MissionPlan("completed", "Planner confirms resumed work."),
            MissionPlan("completed", "Final independent verification passed."),
        ])
        should_stop = threading.Event()

        class FirstRunAgent:
            def run(self, _prompt):
                should_stop.set()
                raise RuntimeError("simulated process interruption")

        first = self.make_engine(planner, lambda _role: FirstRunAgent())
        mission_id = first.create_mission("Resume after interruption")
        partial = first.run(mission_id, should_stop, poll_seconds=0.01, emit=lambda _: None)
        self.assertEqual(partial.status, "active")
        self.assertEqual(partial.pending_tasks, 1)

        class RecoveryAgent:
            def run(self, prompt):
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return '{"passed":true,"findings":[],"tool_evidence":[{"tool":"run_tests","result":"exit_code=0\\nOK"}]}'
                return "recovered: " + prompt

        second = self.make_engine(planner, lambda _role: RecoveryAgent())
        completed = second.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.attempts, 3)

    def test_lost_task_lease_cancels_agent_before_it_can_complete(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Implement one component.", (
                SpecialistTask("component", "code", "implement component"),
            )),
        ])
        stop = threading.Event()
        events = []
        observed = {}

        class WaitingAgent:
            def run(self, prompt, *, cancel_event=None):
                observed["cancel_event"] = cancel_event
                if cancel_event is None:
                    raise AssertionError("mission engine did not pass a cancellation event")
                if cancel_event.wait(8):
                    observed["cancelled"] = True
                    stop.set()
                    raise RuntimeError("agent stopped after lease loss")
                return "must not be accepted after a lost lease"

        engine = ContinuousDevelopmentEngine(
            self.db, planner, lambda _role: WaitingAgent(),
            retry_base_seconds=0.01, lease_seconds=10,
        )

        def lose_lease(_task_id, _worker_id):
            raise RuntimeError("simulated task lease loss")

        engine._heartbeat = lose_lease
        mission_id = engine.create_mission("Stop stale worker writes")
        result = engine.run(mission_id, stop, poll_seconds=0.01, emit=events.append)

        self.assertTrue(observed.get("cancelled"))
        self.assertEqual(result.status, "active")
        self.assertEqual(result.completed_tasks, 0)
        self.assertEqual(result.pending_tasks, 1)
        self.assertTrue(any('"event": "task_interrupted"' in event for event in events))

    def test_dependency_order_is_respected_within_a_mission_batch(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Two dependent tasks.", (
                SpecialistTask("integrate", "integration", "integrate", ("foundation",)),
                SpecialistTask("foundation", "core", "create contract"),
            )),
            MissionPlan("completed", "Planner confirms both tasks succeeded."),
            MissionPlan("completed", "Final independent verification passed."),
        ])
        calls = []

        class Agent:
            def __init__(self, role):
                self.role = role

            def run(self, prompt):
                calls.append((self.role, prompt))
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return '{"passed":true,"findings":[],"tool_evidence":[{"tool":"run_tests","result":"exit_code=0\\nOK"}]}'
                return "ok"

        engine = self.make_engine(planner, lambda role: Agent(role))
        mission_id = engine.create_mission("Build and integrate")
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)
        self.assertEqual(result.status, "completed")
        self.assertEqual(calls[0], ("core", "create contract"))
        self.assertEqual(calls[1][0], "integration")
        self.assertIn("COMPLETED DEPENDENCY RESULTS", calls[1][1])
        self.assertIn("foundation (core)", calls[1][1])
        self.assertIn("ok", calls[1][1])


    def test_terminal_failure_marks_same_cycle_dependants_failed(self):
        engine = self.make_engine(SequencePlanner([]), lambda role: None, max_task_failures=1)
        mission_id = engine.create_mission("Stop dependants after a terminal prerequisite failure.")
        now = time.time()
        prereq = f"{mission_id}:1:prereq"
        direct = f"{mission_id}:1:direct"
        nested = f"{mission_id}:1:nested"
        independent = f"{mission_id}:1:independent"
        with closing(sqlite3.connect(self.db)) as db, db:
            for task_id, dependencies in (
                (prereq, []), (direct, ["prereq"]), (nested, ["direct"]), (independent, []),
            ):
                db.execute("""
                    INSERT INTO development_mission_tasks
                    (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                     failure_count,last_error_class,result,last_error,available_at,worker_id,
                     lease_until,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    task_id, mission_id, 1, "code", task_id, json.dumps(dependencies), "queued", 1,
                    0, "", "", "", now, "", None, now, now,
                ))
            db.execute(
                "UPDATE development_mission_tasks SET status='running',worker_id='worker',lease_until=? WHERE task_id=?",
                (now + 10, prereq),
            )
        status = engine._finish_task(prereq, "worker", error="model action protocol remained invalid")
        self.assertEqual(status, "failed")
        with closing(sqlite3.connect(self.db)) as db, db:
            rows = {
                row[0]: (row[1], row[2])
                for row in db.execute(
                    "SELECT task_id,status,last_error FROM development_mission_tasks WHERE mission_id=?",
                    (mission_id,),
                )
            }
        self.assertEqual(rows[prereq][0], "failed")
        self.assertEqual(rows[direct][0], "failed")
        self.assertEqual(rows[nested][0], "failed")
        self.assertEqual(rows[independent][0], "queued")
        self.assertIn("Prerequisite task did not succeed.", rows[direct][1])
        self.assertIn("Prerequisite task did not succeed.", rows[nested][1])

    def test_failed_independent_verification_forces_repair_and_a_new_verification(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Implement the change.", (
                SpecialistTask("change", "code", "implement the change"),
            )),
            MissionPlan("completed", "Planner prematurely proposes completion."),
            MissionPlan("completed", "Planner again proposes completion after repair."),
            MissionPlan("completed", "Planner requests the post-repair final verification."),
            MissionPlan("completed", "Final verification now passed."),
        ])
        calls = []

        class Agent:
            def __init__(self, role):
                self.role = role

            def run(self, prompt):
                calls.append(self.role)
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    if calls.count("ai_testing_agent") == 1:
                        return '{"passed":false,"findings":["fix failing assertion"],"tool_evidence":[{"tool":"run_tests","result":"exit_code=1\\nFAILED"}]}'
                    return '{"passed":true,"findings":[],"tool_evidence":[{"tool":"run_tests","result":"exit_code=0\\nOK"}]}'
                return "repair applied and tests rerun"

        engine = self.make_engine(planner, lambda role: Agent(role))
        mission_id = engine.create_mission("Implement and verify a change")
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)
        self.assertEqual(result.status, "completed")
        self.assertEqual(calls, ["code", "ai_testing_agent", "ai_repair_agent", "ai_testing_agent"])

    def test_checkpoint_cleanup_failure_does_not_turn_a_saved_success_into_a_retry(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Implement the component.", (
                SpecialistTask("component", "code", "implement the component"),
            )),
            MissionPlan("completed", "Implementation is ready for final verification."),
            MissionPlan("completed", "Final verification passed."),
        ])
        events = []

        class BrokenCheckpointStore:
            def complete(self, _task_id):
                raise OSError("temporary checkpoint cleanup failure")

        class Agent:
            def __init__(self):
                self.checkpoints = BrokenCheckpointStore()

            def run(self, prompt):
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return '{"passed":true,"findings":[],"tool_evidence":[{"tool":"run_tests","result":"exit_code=0\\nOK"}]}'
                return "component implemented"

        engine = self.make_engine(planner, lambda _role: Agent())
        mission_id = engine.create_mission("Keep persisted task success truthful")
        result = engine.run(
            mission_id, threading.Event(), poll_seconds=0.01,
            emit=events.append,
        )

        parsed = [json.loads(event) for event in events]
        self.assertEqual(result.status, "completed")
        self.assertEqual(sum(item["event"] == "task_succeeded" for item in parsed), 2)
        self.assertEqual(sum(item["event"] == "checkpoint_cleanup_warning" for item in parsed), 2)
        self.assertFalse(any(item["event"] == "task_retry_scheduled" for item in parsed))

    def test_empty_specialist_output_is_not_persisted_as_task_success(self):
        planner = SequencePlanner([
            MissionPlan("continue", "Run an empty-output task.", (
                SpecialistTask("empty-output", "code", "return no content"),
            )),
        ])
        events = []

        class EmptyAgent:
            def run(self, _prompt):
                return "   "

        engine = self.make_engine(planner, lambda _role: EmptyAgent())
        mission_id = engine.create_mission("Reject empty specialist output")
        engine._claim_planning(mission_id, "planner")
        engine._store_plan(mission_id, "planner", 1, planner.plans[0])
        task = engine._claim_task(mission_id, "worker")
        self.assertIsNotNone(task)
        engine._execute_task(task, "worker", events.append)
        snapshot = engine.get_mission(mission_id)
        self.assertEqual(snapshot.completed_tasks, 0)
        self.assertEqual(snapshot.pending_tasks, 1)
        self.assertTrue(any('"event": "task_retry_scheduled"' in event for event in events))

    def test_expired_planning_lease_cannot_commit_a_stale_plan(self):
        planner = SequencePlanner([])
        engine = self.make_engine(planner, lambda _role: None)
        mission_id = engine.create_mission("Reject stale planner output")
        claim = engine._claim_planning(mission_id, "worker-one")
        self.assertIsNotNone(claim)

        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute(
                "UPDATE development_missions SET planning_lease_until=0 WHERE mission_id=?",
                (mission_id,),
            )

        with self.assertRaisesRegex(Exception, "Planning lease was lost"):
            engine._store_plan(
                mission_id, "worker-one", 1,
                MissionPlan("continue", "This stale plan must not be saved.", (
                    SpecialistTask("stale", "code", "must not run"),
                )),
            )
        self.assertEqual(engine.get_mission(mission_id).cycle, 0)
        self.assertEqual(engine.get_mission(mission_id).pending_tasks, 0)

    def test_transient_planner_failure_is_retried_without_abandoning_the_mission(self):
        class FlakyPlanner:
            def __init__(self):
                self.calls = 0

            def plan(self, goal, progress, *, mission_id, cycle):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary model endpoint failure")
                if self.calls == 2:
                    return MissionPlan("continue", "Implement the requested component.", (
                        SpecialistTask("component", "code", "implement the component"),
                    ))
                if self.calls == 3:
                    return MissionPlan("completed", "Implementation is ready for independent verification.")
                return MissionPlan("completed", "Independent verification passed.")

        planner = FlakyPlanner()
        events = []

        class Agent:
            def run(self, prompt):
                if "STREAMIOV_FINAL_VERIFICATION" in prompt:
                    return '{"passed":true,"findings":[],"tool_evidence":[{"tool":"run_tests","result":"exit_code=0\\nOK"}]}'
                return "component implemented"

        engine = self.make_engine(planner, lambda _role: Agent())
        mission_id = engine.create_mission("Complete a component despite a temporary planner outage")
        result = engine.run(
            mission_id, threading.Event(), poll_seconds=0.01,
            emit=events.append,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(planner.calls, 4)
        self.assertTrue(any('"event": "planning_retry_scheduled"' in event for event in events))

    def test_invalid_empty_continuation_is_retried_and_not_marked_complete(self):
        stop = threading.Event()
        events = []

        class InvalidPlanOnce:
            def plan(self, goal, progress, *, mission_id, cycle):
                stop.set()
                return MissionPlan("continue", "No work listed.", ())

        engine = self.make_engine(InvalidPlanOnce(), lambda _role: None)
        mission_id = engine.create_mission("Must not be falsely completed")
        result = engine.run(mission_id, stop, poll_seconds=0.01, emit=events.append)

        self.assertEqual(result.status, "active")
        self.assertEqual(result.pending_tasks, 0)
        self.assertTrue(any('"event": "planning_retry_scheduled"' in event for event in events))

    def test_local_recovery_provider_shortens_quota_retry(self):
        class LocalReadyProvider:
            def check_ready(self):
                return {"providers": [{"provider": "ollama", "ready": True}]}

        engine = self.make_engine(
            SequencePlanner([]), lambda _role: None, provider=LocalReadyProvider(),
        )
        mission_id = engine.create_mission("Retry quota failure with the configured free local provider")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""
                INSERT INTO development_mission_tasks
                (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                 result,last_error,available_at,worker_id,lease_until,created_at,updated_at)
                VALUES(?,?,?,?,?,'[]','running',1,'','',0,'worker',?,0,0)
            """, (
                f"{mission_id}:1:local-recovery", mission_id, 1, "code",
                "use local recovery", time.time() + 300,
            ))
        before = time.time()
        status = engine._finish_task(
            f"{mission_id}:1:local-recovery", "worker",
            error="CloudflareWorkerError: HTTP 429 (code: daily_ai_limit_reached)",
        )
        with closing(sqlite3.connect(self.db)) as db, db:
            available_at = db.execute(
                "SELECT available_at FROM development_mission_tasks WHERE task_id=?",
                (f"{mission_id}:1:local-recovery",),
            ).fetchone()[0]
        self.assertEqual(status, "queued")
        self.assertGreaterEqual(available_at - before, 45 - 1)
        self.assertLess(available_at - before, 5 * 60)

    def test_quota_deferred_tasks_do_not_block_replanning_with_local_recovery(self):
        class LocalReadyProvider:
            def check_ready(self):
                return {"providers": [{"provider": "ollama", "ready": True}]}

        engine = self.make_engine(
            SequencePlanner([]), lambda _role: None, provider=LocalReadyProvider(),
        )
        mission_id = engine.create_mission("Keep planning while quota tasks are deferred")
        with closing(sqlite3.connect(self.db)) as db, db:
            for index in range(3):
                db.execute("""
                    INSERT INTO development_mission_tasks
                    (task_id,mission_id,cycle,specialist,prompt,depends_on,status,attempts,
                     result,last_error,last_error_class,available_at,worker_id,lease_until,created_at,updated_at)
                    VALUES(?,?,?,?,?,'[]','queued',1,'','quota','daily_ai_quota',?,'',NULL,0,0)
                """, (
                    f"{mission_id}:1:quota-{index}", mission_id, 1, "code",
                    "deferred by quota", time.time() + 3600,
                ))
        claim = engine._claim_planning(mission_id, "planner")
        self.assertEqual(claim, ("Keep planning while quota tasks are deferred", 1))

    def test_final_verification_uses_observed_test_output_without_a_model_call(self):
        calls = []
        project_root = str(Path(self.temp.name).resolve())

        class Agent:
            def __init__(self):
                self.tools = SimpleNamespace(
                    root=project_root,
                    workspace_store=None,
                    workspace_task_id=None,
                )

            def run(self, prompt, **_kwargs):
                calls.append(prompt)
                raise AssertionError("deterministic verification must not call the model")

        engine = self.make_engine(
            SequencePlanner([]), lambda _role: Agent(),
            verification_runner=lambda _root: "exit_code=0\nRan 785 tests OK",
        )
        mission_id = engine.create_mission("Verify with an observed local test command")
        plan = MissionPlan("continue", "Independent verification.", (
            SpecialistTask(
                "mandatory-final-verification", "ai_testing_agent",
                "STREAMIOV_FINAL_VERIFICATION: verify the mission",
            ),
        ))
        engine._claim_planning(mission_id, "planner")
        engine._store_plan(mission_id, "planner", 2, plan)
        task = engine._claim_task(mission_id, "worker")
        self.assertIsNotNone(task)
        engine._execute_task(task, "worker", lambda _message: None)
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute(
                "SELECT status,result FROM development_mission_tasks WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        self.assertEqual(row[0], "succeeded")
        report = json.loads(row[1])
        self.assertTrue(report["passed"])
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["tool_evidence"][0]["tool"], "run_tests")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
