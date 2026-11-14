import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from ai.core.orchestrator import SpecialistTask
from ai.runtime.continuous_engine import (
    ContinuousDevelopmentEngine,
    MissionEngineError,
    MissionPlan,
    ModelMissionPlanner,
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

    def test_progress_context_stays_within_provider_budget_and_keeps_latest_outcomes(self):
        engine = self.make_engine(SequencePlanner([]), lambda _role: None)
        mission_id = engine.create_mission("Keep planning requests bounded")
        with sqlite3.connect(self.db) as db:
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
        self.assertIn("at most one task per specialist", provider.system)
        self.assertEqual(len({task.prompt for task in plan.tasks}), 11)

        duplicate_aliases = [
            {"id": "legacy-core", "specialist": "core", "prompt": "Research the model runtime.", "depends_on": []},
            {"id": "research", "specialist": "research", "prompt": "Build the model runtime.", "depends_on": []},
        ]
        with self.assertRaisesRegex(MissionEngineError, "multiple tasks in one planning cycle"):
            ModelMissionPlanner(Provider(duplicate_aliases)).plan(
                "Build AI infrastructure.", "", mission_id="duplicate-specialist", cycle=1,
            )

    def test_mission_continues_across_unbounded_planning_cycles_until_explicit_completion(self):
        planner = SequencePlanner([
            MissionPlan("continue", "First phase recorded.", (
                SpecialistTask("foundation", "core", "build foundation"),
            )),
            MissionPlan("continue", "Second phase recorded.", (
                SpecialistTask("verification", "testing", "verify foundation"),
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
                    return '{"verdict":"passed","evidence":["unit tests completed successfully"],"findings":[]}'
                return f"verified: {prompt}"

        engine = self.make_engine(planner, lambda role: Agent(role))
        mission_id = engine.create_mission("Complete the platform")
        events = []
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=events.append)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.cycle, 3)
        self.assertEqual(result.completed_tasks, 3)
        self.assertEqual([item[0] for item in calls], ["core", "testing", "testing"])
        self.assertEqual(len(planner.calls), 4)
        saved_plans = [json.loads(event) for event in events if '"event": "plan_saved"' in event]
        enforced_verification = next(item for item in saved_plans if item["cycle"] == 3)
        self.assertEqual(enforced_verification["state"], "continue")
        self.assertEqual(enforced_verification["task_count"], 1)

    def test_failed_task_retries_without_a_fixed_attempt_ceiling_and_recovers(self):
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
                    return '{"verdict":"passed","evidence":["component tests passed"],"findings":[]}'
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
                    return '{"verdict":"passed","evidence":["recovery tests passed"],"findings":[]}'
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
        self.assertTrue(any('"event": "task_retry_scheduled"' in event for event in events))

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
                    return '{"verdict":"passed","evidence":["dependency and integration tests passed"],"findings":[]}'
                return "ok"

        engine = self.make_engine(planner, lambda role: Agent(role))
        mission_id = engine.create_mission("Build and integrate")
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)
        self.assertEqual(result.status, "completed")
        self.assertEqual(calls[0], ("core", "create contract"))
        self.assertEqual(calls[1], ("integration", "integrate"))


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
                    if calls.count("testing") == 1:
                        return '{"verdict":"failed","evidence":["unit test failed"],"findings":["fix failing assertion"]}'
                    return '{"verdict":"passed","evidence":["unit tests passed after repair"],"findings":[]}'
                return "repair applied and tests rerun"

        engine = self.make_engine(planner, lambda role: Agent(role))
        mission_id = engine.create_mission("Implement and verify a change")
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)
        self.assertEqual(result.status, "completed")
        self.assertEqual(calls, ["code", "testing", "repair", "testing"])

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
                    return '{"verdict":"passed","evidence":["component tests passed"],"findings":[]}'
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

    def test_expired_planning_lease_cannot_commit_a_stale_plan(self):
        planner = SequencePlanner([])
        engine = self.make_engine(planner, lambda _role: None)
        mission_id = engine.create_mission("Reject stale planner output")
        claim = engine._claim_planning(mission_id, "worker-one")
        self.assertIsNotNone(claim)

        with sqlite3.connect(self.db) as db:
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
                    return '{"verdict":"passed","evidence":["component test suite passed"],"findings":[]}'
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


if __name__ == "__main__":
    unittest.main()
