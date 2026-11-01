import tempfile
import unittest
from pathlib import Path

from ai.core.agent import DevelopmentAgent
from ai.runtime.learning_store import LearningStoreError, VerifiedLearningStore


class FakeProvider:
    def __init__(self):
        self.messages = None
    def generate(self, *, system, messages):
        self.messages = messages
        class Reply:
            content = '{"final":"completed"}'
        return Reply()


class VerifiedLearningStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "state" / "lessons.sqlite3"
        self.store = VerifiedLearningStore(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_records_and_retrieves_only_passing_test_backed_lessons(self):
        lesson_id = self.store.record_verified_lesson(
            specialist="studio",
            topic="camera permission handling",
            lesson="Check permission state before opening capture and stop media tracks after preview.",
            regression_test="tests/test_studio_scene_ui.py",
            verification_ref="https://github.com/example/repo/actions/runs/12345",
            test_exit_code=0,
        )
        results = self.store.search("camera capture permission", specialist="studio")
        self.assertEqual(results[0]["lesson_id"], lesson_id)
        self.assertTrue(results[0]["verified"])
        self.assertEqual(results[0]["regression_test"], "tests/test_studio_scene_ui.py")

    def test_core_lessons_are_available_to_specialists(self):
        self.store.record_verified_lesson(
            specialist="core",
            topic="event contract versioning",
            lesson="Keep event schemas versioned and reject unknown required fields.",
            regression_test="tests/test_agent_orchestrator.py",
            verification_ref="commit:abc123",
            test_exit_code=0,
        )
        self.assertEqual(len(self.store.search("event schema versioning", specialist="studio")), 1)

    def test_rejects_failed_tests_secrets_and_unsafe_regression_paths(self):
        base = {
            "specialist": "code",
            "topic": "safe example",
            "lesson": "A normal engineering note.",
            "regression_test": "tests/test_example.py",
            "verification_ref": "commit:abc123",
            "test_exit_code": 0,
        }
        with self.assertRaises(LearningStoreError):
            self.store.record_verified_lesson(**{**base, "test_exit_code": 1})
        with self.assertRaises(LearningStoreError):
            self.store.record_verified_lesson(**{**base, "lesson": "Set API_KEY=secret-value"})
        with self.assertRaises(LearningStoreError):
            self.store.record_verified_lesson(**{**base, "regression_test": "tests/../secrets/test.py"})
        self.assertEqual(self.store.search("safe example"), [])

    def test_specialist_agent_receives_relevant_notes_as_untrusted_reference(self):
        self.store.record_verified_lesson(
            specialist="code",
            topic="safe parser",
            lesson="Reject malformed JSON before executing any tool action.",
            regression_test="tests/test_agent_response_parsing.py",
            verification_ref="commit:def456",
            test_exit_code=0,
        )
        provider = FakeProvider()
        with tempfile.TemporaryDirectory() as root:
            agent = DevelopmentAgent(provider, root, specialist="code", learning_store=self.store)
            self.assertEqual(agent.run("Improve the JSON parser safely"), "completed")
        self.assertIn("Reject malformed JSON", provider.messages[0]["content"])
        self.assertIn("untrusted reference notes", provider.messages[0]["content"])

    def test_no_matching_notes_do_not_change_the_task(self):
        provider = FakeProvider()
        with tempfile.TemporaryDirectory() as root:
            agent = DevelopmentAgent(provider, root, specialist="code", learning_store=self.store)
            agent.run("Task without prior lessons")
        self.assertEqual(provider.messages[0]["content"], "Task without prior lessons")


if __name__ == "__main__":
    unittest.main()
