"""Tests for the local community forum store and HTTP API."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from host.auth import User
from host.forum import (
    ForumError,
    ForumStore,
    validate_reply_body,
    validate_thread_body,
    validate_title,
)
from host.server import Handler, StreamioVHTTPServer


def _user(name="Forum_User", user_id="a" * 32):
    return User(user_id=user_id, username=name, created_at=1)


class ForumValidationTests(unittest.TestCase):
    def test_title_is_single_line_and_length_bounded(self):
        self.assertEqual(validate_title("  Hallo Welt  "), "Hallo Welt")
        for bad in ("", "ab", "a\nb", "a\tb", "x" * 141, None, 42):
            with self.subTest(value=bad):
                with self.assertRaises(ForumError):
                    validate_title(bad)

    def test_body_rejects_control_characters_and_oversized_input(self):
        self.assertEqual(validate_thread_body("Zeile 1\r\nZeile 2"), "Zeile 1\nZeile 2")
        with self.assertRaises(ForumError):
            validate_thread_body("")
        with self.assertRaises(ForumError):
            validate_thread_body("bad\x00nul")
        with self.assertRaises(ForumError):
            validate_thread_body("bad\x01control")
        with self.assertRaises(ForumError):
            validate_thread_body("x" * 10_001)
        with self.assertRaises(ForumError):
            validate_reply_body("x" * 5_001)


class ForumStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.store = ForumStore(self._directory.name)

    def tearDown(self):
        self._directory.cleanup()

    def test_threads_and_replies_round_trip_in_creation_order(self):
        thread = self.store.create_thread(_user(), "Erstes Thema", "Ein Beitrag")
        self.assertEqual(thread["title"], "Erstes Thema")
        self.assertEqual(thread["author"], "Forum_User")
        self.assertEqual(thread["reply_count"], 0)
        self.assertEqual(thread["replies"], [])

        first = self.store.create_reply(_user(), thread["id"], "Erste Antwort")
        second = self.store.create_reply(_user("Second", "b" * 32), thread["id"], "Zweite Antwort")
        detail = self.store.get_thread(thread["id"])
        self.assertEqual([reply["id"] for reply in detail["replies"]], [first["id"], second["id"]])
        self.assertEqual(detail["reply_count"], 2)
        self.assertEqual(detail["last_activity"], second["created_at"])

        listing = self.store.list_threads()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["id"], thread["id"])

    def test_unknown_or_malformed_ids_are_not_found(self):
        self.assertIsNone(self.store.get_thread("missing"))
        self.assertIsNone(self.store.get_thread("A" * 32))
        self.assertIsNone(self.store.get_thread(None))
        with self.assertRaises(ForumError):
            self.store.create_reply(_user(), "missing", "Antwort")

    def test_locking_blocks_new_replies(self):
        thread = self.store.create_thread(_user(), "Gesperrt", "Beitrag")
        self.assertTrue(self.store.set_locked(thread["id"], True))
        self.assertTrue(self.store.get_thread(thread["id"])["locked"])
        with self.assertRaises(ForumError):
            self.store.create_reply(_user(), thread["id"], "Antwort")
        self.assertTrue(self.store.set_locked(thread["id"], False))
        self.assertFalse(self.store.get_thread(thread["id"])["locked"])
        self.assertTrue(self.store.create_reply(_user(), thread["id"], "Antwort"))

    def test_soft_deletes_hide_entries_but_keep_them_for_moderation(self):
        thread = self.store.create_thread(_user(), "Zu löschen", "Beitrag")
        reply = self.store.create_reply(_user(), thread["id"], "Antwort")
        self.assertTrue(self.store.delete_reply(reply["id"]))
        self.assertEqual(self.store.get_thread(thread["id"])["reply_count"], 0)
        self.assertTrue(self.store.delete_thread(thread["id"]))
        self.assertIsNone(self.store.get_thread(thread["id"]))
        self.assertEqual(self.store.list_threads(), [])
        snapshot = self.store.moderation_snapshot()
        self.assertEqual({item["kind"] for item in snapshot}, {"thread", "reply"})
        self.assertTrue(all(item["deleted"] for item in snapshot))
        self.assertFalse(self.store.delete_thread(thread["id"]))

    def test_deleted_thread_is_locked_against_replies(self):
        thread = self.store.create_thread(_user(), "Entfernt", "Beitrag")
        self.store.delete_thread(thread["id"])
        with self.assertRaises(ForumError):
            self.store.create_reply(_user(), thread["id"], "Antwort")


class ForumStaticPageTests(unittest.TestCase):
    def test_page_uses_the_real_forum_api_and_account_session(self):
        page = (Path(__file__).resolve().parents[1] / "dist" / "streamiov-homepage-worker"
                / "public" / "forum" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/forum/threads", page)
        self.assertIn("/api/v1/auth/me", page)
        self.assertIn('href="/account/"', page)
        self.assertIn('credentials:"same-origin"', page)
        self.assertIn("Retry-After", page)
        self.assertNotIn("noch nicht freigeschaltet", page)
        self.assertNotIn('id="author"', page)


class ForumHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        root = Path(cls._directory.name)
        (root / "index.html").write_text("StreamioV forum host", encoding="utf-8")
        cls.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, root, root / "state",
            registration_open=True,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.origin = cls.base
        cls.cookie = cls._register()

    @classmethod
    def _register(cls):
        body = json.dumps({
            "username": "Forum_User",
            "password": "a-long-local-password",
        }).encode()
        request = Request(cls.base + "/api/v1/auth/register", data=body, method="POST", headers={
            "Content-Type": "application/json", "Origin": cls.origin,
        })
        with urlopen(request, timeout=5) as response:
            return response.headers["Set-Cookie"].split(";", 1)[0]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls._directory.cleanup()

    def setUp(self):
        self.server.forum_thread_limiter._attempts.clear()
        self.server.forum_reply_limiter._attempts.clear()

    def _json(self, path, *, method=None, payload=None, cookie=None, origin=None):
        if method is None:
            method = "POST" if payload is not None else "GET"
        headers = {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        if origin:
            headers["Origin"] = origin
        request = Request(self.base + path, data=data, method=method, headers=headers)
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def _error(self, path, *, method="POST", payload=None, cookie=None, origin=None):
        headers = {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        if origin:
            headers["Origin"] = origin
        request = Request(self.base + path, data=data, method=method, headers=headers)
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        return error.exception

    def test_status_reports_the_forum_without_claiming_a_full_api(self):
        _, status = self._json("/api/v1/status")
        self.assertTrue(status["forum_ready"])
        self.assertFalse(status["forum_read_only"])
        self.assertTrue(status["forum_writes_require_session"])
        self.assertFalse(status["api_ready"])

    def test_public_reads_do_not_require_a_session(self):
        _, created = self._json("/api/forum/threads", payload={
            "title": "Öffentlich", "body": "Jeder darf lesen",
        }, cookie=self.cookie, origin=self.origin)
        thread_id = created["thread"]["id"]

        _, listing = self._json("/api/forum/threads")
        self.assertTrue(listing["ok"])
        self.assertIn(thread_id, [thread["id"] for thread in listing["threads"]])

        _, detail = self._json(f"/api/forum/threads/{thread_id}")
        self.assertEqual(detail["thread"]["title"], "Öffentlich")

        error = self._error("/api/forum/threads/" + "0" * 32, method="GET")
        self.assertEqual(error.code, 404)

    def test_writes_require_a_session(self):
        error = self._error("/api/forum/threads", payload={
            "title": "Kein Login", "body": "Text",
        }, origin=self.origin)
        self.assertEqual(error.code, 401)
        self.assertEqual(json.loads(error.read())["error"], "authentication_required")

    def test_writes_require_an_exact_same_origin(self):
        error = self._error("/api/forum/threads", payload={
            "title": "Falscher Origin", "body": "Text",
        }, cookie=self.cookie, origin="https://attacker.example")
        self.assertEqual(error.code, 403)

        error = self._error("/api/forum/threads", payload={
            "title": "Kein Origin", "body": "Text",
        }, cookie=self.cookie)
        self.assertEqual(error.code, 403)

    def test_thread_and_reply_flow(self):
        status, created = self._json("/api/forum/threads", payload={
            "title": "Frage", "body": "Wie geht das?",
        }, cookie=self.cookie, origin=self.origin)
        self.assertEqual(status, 201)
        thread_id = created["thread"]["id"]

        status, reply = self._json(f"/api/forum/threads/{thread_id}/replies", payload={
            "body": "So geht das.",
        }, cookie=self.cookie, origin=self.origin)
        self.assertEqual(status, 201)
        self.assertEqual(reply["reply"]["author"], "Forum_User")

        _, detail = self._json(f"/api/forum/threads/{thread_id}")
        self.assertEqual(detail["thread"]["reply_count"], 1)
        self.assertEqual(detail["thread"]["replies"][0]["body"], "So geht das.")

    def test_payloads_are_strictly_validated(self):
        cases = [
            {"title": "Nur Titel"},
            {"title": "Titel", "body": "Text", "extra": True},
            {"title": "ab", "body": "Text"},
            {"title": "Titel", "body": "x" * 10_001},
        ]
        for payload in cases:
            with self.subTest(payload=str(payload)[:40]):
                error = self._error("/api/forum/threads", payload=payload,
                                    cookie=self.cookie, origin=self.origin)
                self.assertEqual(error.code, 400)

        error = self._error("/api/forum/threads", payload={"body": "Text"},
                            cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 400)

        # A non-JSON content type is rejected before the body is parsed.
        self.server.forum_thread_limiter._attempts.clear()
        request = Request(self.base + "/api/forum/threads", data=b"title=x", method="POST", headers={
            "Content-Type": "text/plain", "Origin": self.origin, "Cookie": self.cookie,
        })
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 400)

    def test_thread_creation_is_rate_limited_per_client(self):
        for index in range(5):
            status, _ = self._json("/api/forum/threads", payload={
                "title": f"Thema {index}", "body": "Text",
            }, cookie=self.cookie, origin=self.origin)
            self.assertEqual(status, 201)
        error = self._error("/api/forum/threads", payload={
            "title": "Zu viel", "body": "Text",
        }, cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 429)
        self.assertEqual(error.headers["Retry-After"], "600")

    def test_locked_and_missing_threads_reject_replies(self):
        _, created = self._json("/api/forum/threads", payload={
            "title": "Sperren", "body": "Text",
        }, cookie=self.cookie, origin=self.origin)
        thread_id = created["thread"]["id"]
        self.assertTrue(self.server.forum_store.set_locked(thread_id, True))

        error = self._error(f"/api/forum/threads/{thread_id}/replies", payload={
            "body": "Antwort",
        }, cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 423)

        error = self._error("/api/forum/threads/" + "0" * 32 + "/replies", payload={
            "body": "Antwort",
        }, cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 404)

    def test_unsupported_methods_are_rejected(self):
        error = self._error("/api/forum/threads", method="DELETE",
                            cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 405)


if __name__ == "__main__":
    unittest.main()
