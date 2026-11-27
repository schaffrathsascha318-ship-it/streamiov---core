"""HTTP tests for the local event ledger API."""
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from host.server import Handler, StreamioVHTTPServer


class EventApiTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        (self.root / "index.html").write_text("ok", encoding="utf-8")
        self.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, self.root, self.root / "state",
            trust_loopback_proxy=True, registration_open=True,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.origin = f"https://127.0.0.1:{self.server.server_port}"
        account = json.dumps({"username": "EventOwner", "password": "a-long-local-password"}).encode()
        request = Request(self.base + "/api/v1/auth/register", data=account, method="POST", headers={
            "Content-Type": "application/json", "Origin": self.origin,
            "X-Forwarded-Proto": "https",
        })
        with urlopen(request, timeout=5) as response:
            self.cookie = response.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self._directory.cleanup()

    def event(self, **overrides):
        payload = {
            "event_id": str(uuid.uuid4()),
            "schema_version": 1,
            "source": "studio",
            "type": "studio.scene.take",
            "severity": "info",
            "occurred_at": "2026-11-26T12:00:00Z",
            "data": {"scene": "LIVE"},
        }
        payload.update(overrides)
        return payload

    def post(self, event, *, cookie=True, client=True, origin=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = self.cookie
        if client:
            headers["X-Streamiov-Client"] = "studio"
        if origin is not None:
            headers["Origin"] = origin
            headers["X-Forwarded-Proto"] = "https"
        return Request(self.base + "/api/v1/events", data=json.dumps({"event": event}).encode(),
                       method="POST", headers=headers)

    def get(self, *, cookie=True, client=True, query=""):
        headers = {}
        if cookie:
            headers["Cookie"] = self.cookie
        if client:
            headers["X-Streamiov-Client"] = "studio"
        return Request(self.base + "/api/v1/events" + query, headers=headers)

    def assert_status(self, request, expected):
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, expected)
        return json.loads(error.exception.read())

    def test_writes_require_session_client_header_and_real_origin(self):
        event = self.event()
        self.assert_status(self.post(event, cookie=False), 401)
        self.assert_status(self.post(event, client=False), 403)
        self.assert_status(self.post(event, origin="https://attacker.example"), 403)
        with urlopen(self.post(event, origin=self.origin), timeout=5) as response:
            created = json.loads(response.read())
            self.assertEqual(response.status, 201)
        self.assertTrue(created["ok"])
        self.assertEqual(created["event"]["data"], {"scene": "LIVE"})

    def test_unknown_types_are_rejected_and_secrets_are_redacted(self):
        self.assert_status(self.post(self.event(type="platform.gift.fake")), 400)
        event = self.event(data={"streamKey": "secret-key", "rtmp": "rtmps://example/app/key"})
        with urlopen(self.post(event), timeout=5) as response:
            stored = json.loads(response.read())["event"]
        self.assertEqual(stored["data"]["streamKey"], "[REDACTED]")
        self.assertEqual(stored["data"]["rtmp"], "[REDACTED]")
        self.assertNotIn("secret-key", json.dumps(stored))

    def test_list_is_owner_scoped_limited_and_idempotent(self):
        event = self.event()
        with urlopen(self.post(event), timeout=5) as response:
            self.assertEqual(response.status, 201)
        with urlopen(self.post(event), timeout=5) as response:
            duplicate = json.loads(response.read())
            self.assertEqual(response.status, 200)
        self.assertTrue(duplicate["duplicate"])
        with urlopen(self.get(query="?limit=5"), timeout=5) as response:
            listing = json.loads(response.read())
        self.assertEqual([entry["event_id"] for entry in listing["events"]], [event["event_id"]])
        self.assertEqual(listing["schema_version"], 1)
        self.assert_status(self.get(cookie=False), 401)
        self.assert_status(self.get(client=False), 403)

    def test_corrupt_event_store_degrades_health_and_status(self):
        (self.server.data_dir / "events.sqlite3").write_bytes(b"not a database")
        health = self.assert_status(Request(self.base + "/healthz"), 503)
        self.assertFalse(health["stores"]["events"]["ok"])
        with urlopen(self.base + "/api/v1/status", timeout=5) as response:
            status = json.loads(response.read())
        self.assertFalse(status["event_ledger_ready"])
        self.assertEqual(status["event_count"], 0)


if __name__ == "__main__":
    unittest.main()
