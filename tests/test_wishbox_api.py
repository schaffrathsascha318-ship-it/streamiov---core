"""HTTP tests for the local Wunschbox order API."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from host.server import Handler, StreamioVHTTPServer


class FakeMusicCatalog:
    def gate(self, territory, usage):
        return {"tracks": [{
            "id": "trk-1", "title": "Neon Nights", "artist": "StreamioV Band",
            "allowed": True, "state": "allowed", "reasons": [],
        }] if usage == "live_stream" else []}


class WishboxApiTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        (self.root / "index.html").write_text("ok", encoding="utf-8")
        self.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, self.root, self.root / "state",
            trust_loopback_proxy=True, registration_open=True,
        )
        self.server.wishbox_store.music_catalog = FakeMusicCatalog()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.origin = f"https://127.0.0.1:{self.server.server_port}"
        account = json.dumps({"username": "WishOwner", "password": "a-long-local-password"}).encode()
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

    def request(self, path, payload=None, *, cookie=True, client=True, origin=None):
        headers = {}
        if cookie:
            headers["Cookie"] = self.cookie
        if client:
            headers["X-Streamiov-Client"] = "studio"
        if origin is not None:
            headers["Origin"] = origin
            headers["X-Forwarded-Proto"] = "https"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        return Request(self.base + path, data=data, method="POST" if payload is not None else "GET",
                       headers=headers)

    def assert_status(self, request, expected):
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, expected)
        return json.loads(error.exception.read())

    def test_order_submission_requires_session_studio_header_and_origin(self):
        payload = {"text": "Analysiere Echo Grid"}
        self.assert_status(self.request("/api/v1/wishbox/orders", payload, cookie=False), 401)
        self.assert_status(self.request("/api/v1/wishbox/orders", payload, client=False), 403)
        self.assert_status(self.request("/api/v1/wishbox/orders", payload,
                                        origin="https://attacker.example"), 403)

    def test_game_order_full_http_lifecycle_and_event_ledger(self):
        with urlopen(self.request("/api/v1/wishbox/orders", {
            "text": "Kannst du meine Situation in Echo Grid analysieren?",
            "sender": "chat-viewer", "source": "chat",
        }, origin=self.origin), timeout=5) as response:
            self.assertEqual(response.status, 201)
            order = json.loads(response.read())["order"]
        self.assertEqual(order["kind"], "game")
        self.assertEqual(order["intent"], "analysis")
        self.assertEqual(order["status"], "queued")
        order_id = order["id"]
        with urlopen(self.request(f"/api/v1/wishbox/orders/{order_id}"), timeout=5) as response:
            detail = json.loads(response.read())["order"]
        self.assertGreaterEqual(len(detail["history"]), 3)
        with urlopen(self.request(f"/api/v1/wishbox/orders/{order_id}/dispatch", {},
                                  origin=self.origin), timeout=5) as response:
            self.assertEqual(json.loads(response.read())["order"]["status"], "assigned")
        with urlopen(self.request("/api/v1/wishbox/handoffs"), timeout=5) as response:
            handoffs = json.loads(response.read())["handoffs"]
        self.assertEqual([item["id"] for item in handoffs], [order_id])
        self.assertEqual(handoffs[0]["handoff"]["agent"], "gaming")
        with urlopen(self.request(f"/api/v1/wishbox/orders/{order_id}/claim",
                                  {"agent": "gaming-ki"}, origin=self.origin), timeout=5) as response:
            self.assertEqual(json.loads(response.read())["order"]["status"], "in_progress")
        with urlopen(self.request(f"/api/v1/wishbox/orders/{order_id}/complete",
                                  {"result": "Neue Strategie vorgeschlagen"}, origin=self.origin),
                     timeout=5) as response:
            done = json.loads(response.read())["order"]
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"], "Neue Strategie vorgeschlagen")
        with urlopen(self.request("/api/v1/events?limit=20"), timeout=5) as response:
            events = json.loads(response.read())["events"]
        event_types = {event["type"] for event in events}
        self.assertIn("wishbox.order.received", event_types)
        self.assertIn("wishbox.order.result", event_types)

    def test_music_order_is_rights_gated_and_duplicates_are_reported(self):
        with urlopen(self.request("/api/v1/wishbox/orders", {
            "text": "Spiele Neon Nights von StreamioV Band", "sender": "alice",
        }, origin=self.origin), timeout=5) as response:
            order = json.loads(response.read())["order"]
        self.assertEqual(order["status"], "queued")
        self.assertEqual(order["handoff"]["track_id"], "trk-1")
        with urlopen(self.request("/api/v1/wishbox/orders", {
            "text": "Spiele Neon Nights von StreamioV Band", "sender": "bob",
        }, origin=self.origin), timeout=5) as response:
            duplicate = json.loads(response.read())["order"]
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["id"], order["id"])
        with urlopen(self.request("/api/v1/wishbox/orders", {
            "text": "Song ohne Freigabe von Unbekannt",
        }, origin=self.origin), timeout=5) as response:
            rejected = json.loads(response.read())["order"]
        self.assertEqual(rejected["status"], "rejected")

    def test_invalid_state_transition_and_unknown_order_are_rejected(self):
        with urlopen(self.request("/api/v1/wishbox/orders", {
            "text": "Analysiere Neon Relay",
        }, origin=self.origin), timeout=5) as response:
            order_id = json.loads(response.read())["order"]["id"]
        errors = self.assert_status(self.request(
            f"/api/v1/wishbox/orders/{order_id}/complete", {"result": "x"}, origin=self.origin), 400)
        self.assertIn("nicht erlaubt", errors["error"])
        self.assert_status(self.request(
            "/api/v1/wishbox/orders/wish-0123456789abcdef0123456789abcdef/dispatch", {},
            origin=self.origin), 404)
        self.assert_status(self.request("/api/v1/wishbox/unknown", origin=self.origin), 404)

    def test_status_reports_wishbox_readiness(self):
        with urlopen(self.base + "/api/v1/status", timeout=5) as response:
            status = json.loads(response.read())
        self.assertTrue(status["wishbox_endpoint_ready"])
        self.assertTrue(status["wishbox_requires_session"])
        self.assertTrue(status["wishbox_music_orders_require_live_rights"])
        self.assertIn("wishbox", status["stores"])


if __name__ == "__main__":
    unittest.main()
