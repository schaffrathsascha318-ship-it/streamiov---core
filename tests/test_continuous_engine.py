import tempfile
import threading
import unittest
from pathlib import Path

from ai.core.orchestrator import SpecialistTask
from ai.runtime.continuous_engine import (
    ContinuousDevelopmentEngine,
    MissionPlan,
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
        result = engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.cycle, 3)
        self.assertEqual(result.completed_tasks, 3)
        self.assertEqual([item[0] for item in calls], ["core", "testing", "testing"])
        self.assertEqual(len(planner.calls), 4)

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

    def test_invalid_empty_continuation_is_rejected_and_not_marked_complete(self):
        planner = SequencePlanner([MissionPlan("continue", "No work listed.", ())])
        engine = self.make_engine(planner, lambda _role: None)
        mission_id = engine.create_mission("Must not be falsely completed")
        with self.assertRaises(Exception):
            engine.run(mission_id, threading.Event(), poll_seconds=0.01, emit=lambda _: None)
        self.assertEqual(engine.get_mission(mission_id).status, "active")


if __name__ == "__main__":
    unittest.main()
