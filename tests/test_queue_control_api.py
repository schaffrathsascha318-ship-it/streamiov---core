"""Authenticated queue-control HTTP API tests."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from ai.core.orchestrator import SpecialistTask
from ai.runtime.task_queue import SpecialistTaskQueue
from host.auth import AuthStore
from host.server import Handler, StreamioVHTTPServer


class QueueControlAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        data_dir = root / "state"
        auth = AuthStore(data_dir)
        self.admin, self.admin_session = auth.register("Queue_Admin", "a-long-local-password")
        self.other, self.other_session = auth.register("Queue_User", "another-long-password")
        self.queue_db = root / "queue.sqlite3"
        self.queue = SpecialistTaskQueue(self.queue_db)
        self.task_id = "queued-task-001"
        self.queue.enqueue_plan([SpecialistTask(self.task_id, "general", "safe test prompt")])
        self.env = patch.dict(os.environ, {
            "STREAMIOV_TASK_QUEUE_DB": str(self.queue_db),
            "STREAMIOV_QUEUE_ADMIN_USER_IDS": self.admin.user_id,
        })
        self.env.start()
        site = root / "site"
        site.mkdir()
        (site / "index.html").write_text("test", encoding="utf-8")
        self.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, site, data_dir,
            trust_loopback_proxy=True, registration_open=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.origin = f"https://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.env.stop()
        self.temp.cleanup()

    def request(self, path, *, method="GET", session=None, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"X-Forwarded-Proto": "https"}
        if session:
            headers["Cookie"] = "streamiov_session=" + session
        if method == "POST":
            headers["Origin"] = self.origin
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_requires_session_and_explicit_operator_allowlist(self):
        status, body = self.request("/api/v1/queue/status")
        self.assertEqual(status, 401)
        status, body = self.request("/api/v1/queue/status", session=self.other_session)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "queue_operator_forbidden")

    def test_admin_can_pause_resume_cancel_and_read_redacted_audit(self):
        status, body = self.request("/api/v1/queue/pause", method="POST", session=self.admin_session)
        self.assertEqual(status, 200)
        self.assertTrue(body["paused"])
        self.assertTrue(self.queue.is_paused())

        status, body = self.request("/api/v1/queue/status", session=self.admin_session)
        self.assertEqual(status, 200)
        self.assertEqual(body["task_counts"]["queued"], 1)
        self.assertNotIn("prompt", json.dumps(body))

        status, body = self.request(
            f"/api/v1/queue/tasks/{self.task_id}/cancel", method="POST", session=self.admin_session
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "cancelled")

        status, body = self.request("/api/v1/queue/resume", method="POST", session=self.admin_session)
        self.assertEqual(status, 200)
        self.assertFalse(body["paused"])

        status, body = self.request("/api/v1/queue/audit?limit=20", session=self.admin_session)
        self.assertEqual(status, 200)
        actions = [item["action"] for item in body["entries"]]
        self.assertIn("queue.paused", actions)
        self.assertIn("task.cancelled", actions)
        self.assertIn("queue.resumed", actions)
        self.assertTrue(all(item["actor"] == self.admin.user_id for item in body["entries"]
                            if item["action"] in {"queue.paused", "task.cancelled", "queue.resumed"}))
        self.assertTrue(all("details" not in item for item in body["entries"]))

    def test_request_cannot_supply_actor_or_body_for_control_action(self):
        status, body = self.request(
            "/api/v1/queue/pause", method="POST", session=self.admin_session,
            payload={"actor": "attacker"},
        )
        self.assertEqual(status, 400)
        self.assertFalse(self.queue.is_paused())
        self.assertFalse(any(item["actor"] == "attacker" for item in self.queue.audit_log()))

    def test_api_is_disabled_without_explicit_queue_database(self):
        self.server.task_queue = None
        status, body = self.request("/api/v1/queue/status", session=self.admin_session)
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "queue_api_not_configured")


if __name__ == "__main__":
    unittest.main()
