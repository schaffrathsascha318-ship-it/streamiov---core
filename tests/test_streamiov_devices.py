"""Device enrollment and revocation tests for the local Core host."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from host.auth import AuthStore
from host.server import Handler, StreamioVHTTPServer


class DeviceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = AuthStore(Path(self.temp.name) / "state")
        self.user, self.session = self.store.register("Device_Owner", "a-long-local-password")

    def tearDown(self):
        self.temp.cleanup()

    def test_pairing_code_is_single_use_and_device_token_is_hashed(self):
        code, expires = self.store.create_device_pairing_code(self.user.user_id)
        self.assertGreater(expires, 0)
        self.assertNotIn(code.encode("ascii"), self.store.database.read_bytes())
        enrolled = self.store.enroll_device(code, "Pixel test phone", "android")
        self.assertIsNotNone(enrolled)
        device, token = enrolled
        self.assertEqual(device.scopes, ("status:read",))
        self.assertNotIn(token.encode("ascii"), self.store.database.read_bytes())
        self.assertIsNotNone(self.store.user_for_device_token(token))
        self.assertIsNone(self.store.enroll_device(code, "Second phone", "android"))
        self.assertEqual(len(self.store.list_devices(self.user.user_id)), 1)

    def test_revoke_and_password_reset_invalidate_device_credentials(self):
        code, _ = self.store.create_device_pairing_code(self.user.user_id)
        device, token = self.store.enroll_device(code, "Desktop", "windows")
        self.assertTrue(self.store.revoke_device(self.user.user_id, device.device_id))
        self.assertIsNone(self.store.user_for_device_token(token))
        code, _ = self.store.create_device_pairing_code(self.user.user_id)
        _device, token = self.store.enroll_device(code, "Tablet", "android")
        self.assertTrue(self.store.reset_password(self.user.username, "a-new-long-local-password"))
        self.assertIsNone(self.store.user_for_device_token(token))
        self.assertIsNone(self.store.enroll_device(code, "Another device", "ios"))

    def test_expired_pairing_code_cannot_enroll(self):
        code, _ = self.store.create_device_pairing_code(self.user.user_id)
        import sqlite3
        with sqlite3.connect(self.store.database) as db:
            db.execute("UPDATE device_pairing_codes SET expires_at=1")
        self.assertIsNone(self.store.enroll_device(code, "Old phone", "android"))


class DeviceAccountPageTests(unittest.TestCase):
    def test_account_page_contains_responsive_device_management_and_no_token_persistence(self):
        page = Path(__file__).resolve().parents[1] / "dist/streamiov-homepage-worker/public/account/index.html"
        markup = page.read_text(encoding="utf-8")
        for required in (
            'id="login-form"', 'id="pairing-card"', 'id="create-code"',
            'id="enroll-form"', 'id="device-list"', 'id="connection-status"',
            "/api/v1/devices/pairing-code", "/api/v1/devices/enroll",
            "/api/v1/device/status", "/api/v1/devices/", "status:read",
            "currentDeviceToken", "class=\"device\"", "@media(max-width:700px)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, markup)
        self.assertNotIn("localStorage", markup)
        self.assertNotIn("sessionStorage", markup)
        self.assertIn("replaceChildren()", markup)
        self.assertIn("textContent=device.name", markup)


class DeviceHostAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        site = root / "site"
        site.mkdir()
        (site / "index.html").write_text("test", encoding="utf-8")
        self.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, site, root / "state", trust_loopback_proxy=True,
            registration_open=True,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.origin = f"https://127.0.0.1:{self.server.server_port}"
        account = json.dumps({"username": "Device_Host", "password": "a-long-local-password"}).encode()
        request = Request(self.base + "/api/v1/auth/register", data=account, method="POST", headers={
            "Content-Type": "application/json", "Origin": self.origin, "X-Forwarded-Proto": "https",
        })
        with urlopen(request, timeout=5) as response:
            self.cookie = response.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def _request(self, path, *, method="GET", payload=None, headers=None):
        body = None if payload is None else json.dumps(payload).encode()
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=body, method=method, headers=request_headers)
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_pair_enroll_status_list_and_revoke(self):
        owner_headers = {"Cookie": self.cookie, "Origin": self.origin, "X-Forwarded-Proto": "https"}
        status, pairing = self._request("/api/v1/devices/pairing-code", method="POST", headers=owner_headers)
        self.assertEqual(status, 201)
        self.assertTrue(pairing["single_use"])
        status, enrolled = self._request("/api/v1/devices/enroll", method="POST", payload={
            "pairing_code": pairing["pairing_code"], "name": "Chromebook", "platform": "chromeos",
        })
        self.assertEqual(status, 201)
        token = enrolled["device_token"]
        self.assertEqual(enrolled["device"]["scopes"], ["status:read"])
        status, device_status = self._request("/api/v1/device/status", headers={"Authorization": "Bearer " + token})
        self.assertEqual(status, 200)
        self.assertFalse(device_status["task_api_ready"])
        self.assertFalse(device_status["workspace_access"])
        status, devices = self._request("/api/v1/devices", headers={"Cookie": self.cookie})
        self.assertEqual(status, 200)
        self.assertEqual(len(devices["devices"]), 1)
        device_id = enrolled["device"]["device_id"]
        status, revoked = self._request(
            f"/api/v1/devices/{device_id}/revoke", method="POST", headers=owner_headers,
        )
        self.assertEqual(status, 200)
        with self.assertRaises(HTTPError) as error:
            self._request("/api/v1/device/status", headers={"Authorization": "Bearer " + token})
        self.assertEqual(error.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
