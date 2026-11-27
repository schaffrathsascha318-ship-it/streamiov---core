"""Deterministic lifecycle audit for every registered specialist role."""
import json
import tempfile
import unittest
from pathlib import Path

from ai.core.agent import DevelopmentAgent
from ai.core.orchestrator import SpecialistTask, TaskOrchestrator, TaskPlanError
from ai.runtime.task_queue import SpecialistTaskQueue, SpecialistWorker
from ai.specialists.registry import (
    FINAL_VERIFICATION_MARKER,
    FINAL_VERIFICATION_PREFIX,
    FINAL_VERIFICATION_ROLES,
    LEGACY_SPECIALIST_ALIASES,
    VERIFICATION_REPAIR_MARKER,
    VERIFICATION_REPAIR_ROLES,
    get_specialist,
    specialist_names,
    task_prompt_for_specialist,
)


class ScriptedProvider:
    def __init__(self, *, verification: bool, role: str) -> None:
        self.systems: list[str] = []
        if verification:
            replies = [
                '{"tool":"list_files","arguments":{"path":"."}}',
                '{"tool":"run_tests","arguments":{"command":"python -m unittest discover -s tests"}}',
                '{"verdict":"passed","evidence":["Observed the allowlisted baseline test command."],"findings":[]}',
            ]
        else:
            replies = [
                '{"tool":"list_files","arguments":{"path":"."}}',
                json.dumps({"final": f"Observed audit result for {role}."}),
            ]
        self.responses = iter(replies)

    def generate(self, *, system, messages):
        self.systems.append(system)
        content = next(self.responses)

        class Reply:
            pass

        reply = Reply()
        reply.content = content
        return reply


class SpecialistRoleLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.directory.name)
        tests_dir = self.root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_probe.py").write_text(
            "import unittest\n\nclass Probe(unittest.TestCase):\n"
            "    def test_probe(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (self.root / "probe.txt").write_text("role audit fixture\n", encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def test_all_registered_roles_accept_execute_and_hand_back_results(self):
        roles = specialist_names()
        self.assertEqual(len(roles), 28)
        self.assertEqual(len(set(roles)), 28)
        for role in roles:
            with self.subTest(role=role):
                definition = get_specialist(role)
                self.assertEqual(definition.key, role)
                self.assertTrue(definition.mission.strip())
                verification = definition.key in FINAL_VERIFICATION_ROLES
                prompt = task_prompt_for_specialist(role, f"Inspect probe.txt for {role}.")
                if verification:
                    self.assertTrue(prompt.startswith(FINAL_VERIFICATION_PREFIX))
                else:
                    self.assertNotIn(FINAL_VERIFICATION_MARKER, prompt)

                database = self.root / f"queue-{role}.sqlite3"
                queue = SpecialistTaskQueue(database)
                task_id = f"role-audit-{role}"
                queue.enqueue_plan((SpecialistTask(task_id, role, prompt),))
                accepted = queue.get(task_id)
                self.assertIsNotNone(accepted)
                self.assertEqual(accepted.status, "queued")
                self.assertEqual(get_specialist(accepted.specialist).key, role)

                provider = ScriptedProvider(verification=verification, role=role)

                def agent_factory(specialist, *, task_id=None):
                    return DevelopmentAgent(
                        provider, self.root, specialist=specialist,
                        checkpoint_db=str(database) + ".checkpoints", task_id=task_id,
                    )

                worker = SpecialistWorker(queue, f"audit-worker-{role}", agent_factory)
                execution = worker.run_once()
                self.assertEqual(execution.status, "succeeded", execution.error)
                self.assertIn(f"SPECIALIST ROLE: {definition.title} ({role})", provider.systems[0])

                completed = queue.get(task_id)
                self.assertEqual(completed.status, "succeeded")
                self.assertEqual(completed.result, execution.result)
                self.assertTrue(completed.result)
                if verification:
                    report = json.loads(completed.result)
                    self.assertEqual(report["verdict"], "passed")
                    self.assertTrue(any(item.get("tool") == "run_tests" for item in report["tool_evidence"]))
                else:
                    self.assertEqual(completed.result, f"Observed audit result for {role}.")

    def test_all_legacy_aliases_resolve_to_registered_roles(self):
        for alias, canonical in LEGACY_SPECIALIST_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertEqual(get_specialist(alias).key, canonical)
                self.assertIn(canonical, specialist_names())

    def test_reserved_role_markers_are_added_once_and_enforced(self):
        for role in FINAL_VERIFICATION_ROLES:
            prepared = task_prompt_for_specialist(role, "Inspect the work.")
            self.assertEqual(prepared.count(FINAL_VERIFICATION_MARKER), 1)
            self.assertEqual(task_prompt_for_specialist(role, prepared), prepared)
        for role in VERIFICATION_REPAIR_ROLES:
            prepared = task_prompt_for_specialist(role, "Repair the defect.")
            self.assertEqual(prepared.count(VERIFICATION_REPAIR_MARKER), 1)
            self.assertEqual(task_prompt_for_specialist(role, prepared), prepared)

        with self.assertRaises(TaskPlanError):
            TaskOrchestrator(lambda _role: None)._validate_and_order(
                (SpecialistTask("unmarked-verification", "ai_testing_agent", "Inspect the work."),)
            )
        with self.assertRaises(TaskPlanError):
            TaskOrchestrator(lambda _role: None)._validate_and_order(
                (SpecialistTask("unmarked-repair", "ai_repair_agent", "Repair the defect."),)
            )


if __name__ == "__main__":
    unittest.main()
