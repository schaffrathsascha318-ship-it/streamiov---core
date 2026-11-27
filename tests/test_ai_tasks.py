"""Tests for durable local AI task records."""
import tempfile
import unittest
from pathlib import Path

from host.ai_tasks import AITaskError, AITaskStore, validate_request


class AITaskStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.store = AITaskStore(Path(self._directory.name))

    def tearDown(self):
        self._directory.cleanup()

    def test_request_validation_is_bounded(self):
        self.assertEqual(validate_request("  Hallo  "), "Hallo")
        for bad in ("", " " * 2001, None, 42, "bad\x00task"):
            with self.subTest(value=repr(bad)[:30]):
                with self.assertRaises(AITaskError):
                    validate_request(bad)

    def test_created_task_is_persistent_and_owner_scoped(self):
        task = self.store.create("owner", "Erste Aufgabe")
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["request"], "Erste Aufgabe")
        self.assertEqual(self.store.get(task["id"], "owner")["request"], "Erste Aufgabe")
        self.assertIsNone(self.store.get(task["id"], "other"))
        self.assertIsNone(self.store.get("missing", "owner"))

        restarted = AITaskStore(Path(self._directory.name))
        self.assertEqual(restarted.get(task["id"], "owner")["status"], "queued")
        self.assertEqual([item["id"] for item in restarted.list("owner")], [task["id"]])
        self.assertEqual(restarted.list("other"), [])

    def test_completion_and_failure_are_terminal(self):
        completed = self.store.create("owner", "Erfolg")
        self.assertTrue(self.store.mark_running(completed["id"]))
        self.assertFalse(self.store.mark_running(completed["id"]))
        self.assertTrue(self.store.complete(
            completed["id"], answer="Antwort", provider="ollama", model="local-model"
        ))
        self.assertFalse(self.store.fail(completed["id"], "zu spät"))
        final = self.store.get(completed["id"], "owner")
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["answer"], "Antwort")
        self.assertEqual(final["provider"], "ollama")
        self.assertEqual(final["model"], "local-model")
        self.assertEqual(final["error"], "")

        failed = self.store.create("owner", "Fehler")
        self.assertTrue(self.store.fail(failed["id"], "local model missing"))
        self.assertFalse(self.store.complete(
            failed["id"], answer="Antwort", provider="ollama", model="local-model"
        ))
        final = self.store.get(failed["id"], "owner")
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["error"], "local model missing")
        self.assertEqual(final["answer"], "")

    def test_malformed_ids_are_rejected(self):
        with self.assertRaises(AITaskError):
            self.store.create("", "Aufgabe")
        self.assertIsNone(self.store.get("A" * 32, "owner"))
        self.assertFalse(self.store.complete("A" * 32, answer="Antwort", provider="p", model="m"))
        self.assertFalse(self.store.fail("A" * 32, "Fehler"))
        with self.assertRaises(AITaskError):
            self.store.list("")


if __name__ == "__main__":
    unittest.main()
