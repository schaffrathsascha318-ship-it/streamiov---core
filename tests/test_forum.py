"""Tests for the local community forum store and HTTP API."""
from contextlib import closing, redirect_stdout
from io import StringIO
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from host.auth import User
from host.forum import (
    ForumError,
    ForumStore,
    static_spam_flags,
    validate_reply_body,
    validate_report_detail,
    validate_report_reason,
    validate_thread_body,
    validate_title,
)
from host.server import Handler, StreamioVHTTPServer, main


def _user(name="Forum_User", user_id="a" * 32):
    return User(user_id=user_id, username=name, created_at=1)


class ForumValidationTests(unittest.TestCase):
    def test_title_is_single_line_and_length_bounded(self):
        self.assertEqual(validate_title("  Hallo Welt  "), "Hallo Welt")
        for bad in ("", "ab", "a\nb", "a\tb", "x" * 141, None, 42):
            with self.subTest(value=bad):
                with self.assertRaises(ForumError):
                    validate_title(bad)

    def test_report_validation_bounds_reason_and_detail(self):
        self.assertEqual(validate_report_reason("spam"), "spam")
        self.assertEqual(validate_report_detail(None), "")
        self.assertEqual(validate_report_detail("  Grund  "), "Grund")
        for bad in ("", "unknown", None, 42):
            with self.subTest(reason=bad):
                with self.assertRaises(ForumError):
                    validate_report_reason(bad)
        for bad in ("x" * 501, 42, "bad\x00detail"):
            with self.subTest(detail=str(bad)[:20]):
                with self.assertRaises(ForumError):
                    validate_report_detail(bad)
        self.assertIn("repeated_characters", static_spam_flags("AAAAAAAAAA"))
        self.assertIn("many_links", static_spam_flags("http://a.example http://b.example http://c.example http://d.example"))

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


    def test_reports_are_validated_deduplicated_and_resolved(self):
        thread = self.store.create_thread(_user(), "Melden", "Ein Beitrag")
        report = self.store.create_report(
            _user("Reporter", "c" * 32), reason="spam", thread_id=thread["id"],
            detail="Werbung",
        )
        self.assertEqual(report["status"], "open")
        self.assertEqual(len(self.store.list_reports(status="open")), 1)

        with self.assertRaises(ForumError):
            self.store.create_report(_user("Reporter", "c" * 32), reason="spam",
                                     thread_id=thread["id"])
        with self.assertRaises(ForumError):
            self.store.create_report(_user(), reason="unknown", thread_id=thread["id"])
        with self.assertRaises(ForumError):
            self.store.create_report(_user(), reason="spam")
        with self.assertRaises(ForumError):
            self.store.create_report(_user(), reason="spam", thread_id="missing")

        resolver = _user("Moderator", "d" * 32)
        self.assertTrue(self.store.resolve_report(report["id"], status="resolved", resolver=resolver))
        self.assertFalse(self.store.resolve_report(report["id"], status="dismissed", resolver=resolver))
        self.assertEqual(self.store.list_reports(status="open"), [])
        resolved = self.store.list_reports(status="resolved")
        self.assertEqual(resolved[0]["resolved_by"], "d" * 32)
        self.assertIsInstance(resolved[0]["resolved_at"], int)

    def test_report_captures_immutable_target_context(self):
        author = _user("Author", "a" * 32)
        reporter = _user("Reporter", "c" * 32)
        body = "http://a.example http://b.example http://c.example http://d.example"
        thread = self.store.create_thread(author, "Werbung", body)
        report = self.store.create_report(
            reporter, reason="spam", thread_id=thread["id"], detail="Bitte prüfen"
        )
        self.assertEqual(report["kind"], "thread")
        self.assertEqual(report["target_title"], "Werbung")
        self.assertEqual(report["target_body"], body)
        self.assertEqual(report["target_preview"], body[:120])
        self.assertEqual(report["target_author"], "Author")
        self.assertEqual(report["target_author_user_id"], "a" * 32)
        self.assertIn("many_links", report["target_spam_flags"])
        self.assertEqual(report["target_permalink"], "/forum/#t=" + thread["id"])
        self.assertEqual(report["captured_at"], report["created_at"])

        captured = dict(report)
        self.assertTrue(self.store.delete_thread(thread["id"]))
        stored = self.store.list_reports(status="all")[0]
        for key in ("target_title", "target_body", "target_preview", "target_author",
                    "target_author_user_id", "target_spam_flags", "target_permalink"):
            self.assertEqual(stored[key], captured[key])
        self.assertIsNone(self.store.get_thread(thread["id"]))

        reply_thread = self.store.create_thread(author, "Frage", "Inhalt")
        reply = self.store.create_reply(author, reply_thread["id"], "AAAAAAAAAAAAAAAAAAAAAAAA")
        reply_report = self.store.create_report(reporter, reason="other", reply_id=reply["id"])
        self.assertEqual(reply_report["kind"], "reply")
        self.assertEqual(reply_report["target_title"], "Frage")
        self.assertEqual(reply_report["target_body"], reply["body"])
        self.assertEqual(reply_report["target_author"], "Author")
        self.assertIn("repeated_characters", reply_report["target_spam_flags"])
        self.assertTrue(reply_report["target_permalink"].endswith("&r=" + reply["id"]))

    def test_open_report_dedup_is_enforced_by_the_database(self):
        thread = self.store.create_thread(_user(), "Doppelt", "Ein Beitrag")
        reporter = _user("Reporter", "c" * 32)
        first = self.store.create_report(reporter, reason="spam", thread_id=thread["id"])
        with self.assertRaises(ForumError):
            self.store.create_report(reporter, reason="spam", thread_id=thread["id"])
        other = self.store.create_report(
            _user("Other", "b" * 32), reason="spam", thread_id=thread["id"]
        )
        self.assertNotEqual(other["id"], first["id"])

        with closing(sqlite3.connect(self.store.database)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""
                    INSERT INTO forum_reports(
                        report_id, thread_id, reason, reporter_user_id, status, created_at,
                        target_kind, target_key, target_title, target_body,
                        target_author_user_id, target_author_name, target_thread_id,
                        target_spam_flags
                    ) VALUES(?,?,?,?,'open',?,?,?,?,?,?,?,?,'[]')
                """, ("d" * 32, thread["id"], "spam", "c" * 32, 999, "thread",
                      "thread:" + thread["id"], "Doppelt", "Ein Beitrag", "a" * 32,
                      "Forum_User", thread["id"]))

        race_thread = self.store.create_thread(_user(), "Rennen", "Ein Beitrag")
        outcomes = []
        outcomes_lock = threading.Lock()

        def attempt():
            try:
                self.store.create_report(
                    reporter, reason="harassment", thread_id=race_thread["id"]
                )
                with outcomes_lock:
                    outcomes.append("ok")
            except ForumError:
                with outcomes_lock:
                    outcomes.append("duplicate")

        workers = [threading.Thread(target=attempt) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(outcomes), ["duplicate", "ok"])
        open_reports = self.store.list_reports(status="open")
        self.assertEqual(len([item for item in open_reports
                              if item["thread_id"] == race_thread["id"]]), 1)

    def test_decide_report_is_atomic_and_soft_deletes_the_exact_target(self):
        thread = self.store.create_thread(_user("Author", "a" * 32), "Werbung",
                                          "http://a.example http://b.example "
                                          "http://c.example http://d.example")
        report = self.store.create_report(
            _user("Reporter", "c" * 32), reason="spam", thread_id=thread["id"]
        )
        moderator = _user("Mod", "d" * 32)
        result = self.store.decide_report(
            report["id"], "resolved", moderator,
            content_action="delete", note="Werbung entfernt",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["report_id"], report["id"])
        self.assertEqual(result["decision"], "resolved")
        self.assertEqual(result["content_action"], "delete")
        self.assertTrue(result["content_action_applied"])
        self.assertEqual(result["report"]["status"], "resolved")
        self.assertEqual(result["report"]["resolver"], "d" * 32)
        self.assertEqual(result["audit"]["action"], "resolved")
        self.assertEqual(result["audit"]["actor_user_id"], "d" * 32)
        self.assertEqual(result["audit"]["actor_name"], "Mod")
        self.assertEqual(result["audit"]["note"], "Werbung entfernt")
        self.assertEqual(result["content_audit"]["action"], "content_delete")

        self.assertIsNone(self.store.get_thread(thread["id"]))
        snapshot = [item for item in self.store.moderation_snapshot()
                    if item["id"] == thread["id"]]
        self.assertEqual(len(snapshot), 1)
        self.assertTrue(snapshot[0]["deleted"])
        with closing(sqlite3.connect(self.store.database)) as db:
            actions = db.execute(
                "SELECT action, actor_user_id, actor_name, note "
                "FROM forum_moderation_actions"
            ).fetchall()
        self.assertEqual({row[0] for row in actions}, {"resolved", "content_delete"})
        self.assertTrue(all(row[1] == "d" * 32 and row[2] == "Mod"
                            and row[3] == "Werbung entfernt" for row in actions))
        notification = self.store.list_notifications("c" * 32)[0]
        self.assertIn("gelöscht", notification["message"])
        self.assertTrue(notification["unread"])
        self.assertIsNone(
            self.store.decide_report(report["id"], "dismissed", moderator)
        )

    def test_decide_report_uses_lock_unlock_and_only_the_reported_reply(self):
        author = _user("Author", "a" * 32)
        reporter = _user("Reporter", "c" * 32)
        moderator = _user("Mod", "d" * 32)
        thread = self.store.create_thread(author, "Thema", "Beitrag")
        reply = self.store.create_reply(author, thread["id"], "AAAAAAAAAAAAAAAAAAAAAAAA")
        report = self.store.create_report(reporter, reason="spam", reply_id=reply["id"])
        result = self.store.decide_report(
            report["id"], "resolved", moderator, content_action="delete"
        )
        self.assertTrue(result["content_action_applied"])
        detail = self.store.get_thread(thread["id"])
        self.assertIsNotNone(detail)
        self.assertEqual(detail["reply_count"], 0)
        self.assertEqual(detail["replies"], [])

        second_reply = self.store.create_reply(author, thread["id"], "Zweite Antwort")
        reply_report = self.store.create_report(
            reporter, reason="other", reply_id=second_reply["id"]
        )
        with self.assertRaises(ForumError):
            self.store.decide_report(
                reply_report["id"], "resolved", moderator, content_action="lock"
            )
        self.assertIn(reply_report["id"],
                      {item["id"] for item in self.store.list_reports(status="open")})

        lock_thread = self.store.create_thread(author, "Sperren", "Beitrag")
        lock_report = self.store.create_report(
            reporter, reason="harassment", thread_id=lock_thread["id"]
        )
        locked = self.store.decide_report(
            lock_report["id"], "dismissed", moderator, content_action="lock"
        )
        self.assertTrue(locked["content_action_applied"])
        self.assertTrue(self.store.get_thread(lock_thread["id"])["locked"])
        unlock_report = self.store.create_report(
            _user("Other", "b" * 32), reason="offtopic", thread_id=lock_thread["id"]
        )
        unlocked = self.store.decide_report(
            unlock_report["id"], "resolved", moderator, content_action="unlock"
        )
        self.assertTrue(unlocked["content_action_applied"])
        self.assertFalse(self.store.get_thread(lock_thread["id"])["locked"])

    def test_decide_report_validates_inputs_and_ignores_handled_reports(self):
        thread = self.store.create_thread(_user(), "Prüfung", "Beitrag")
        report = self.store.create_report(
            _user("Reporter", "c" * 32), reason="spam", thread_id=thread["id"]
        )
        moderator = _user("Mod", "d" * 32)
        invalid = (
            ("unknown", "none", moderator, None),
            ("resolved", "pause", moderator, None),
            ("resolved", "none", object(), None),
            ("resolved", "none", moderator, "x" * 501),
        )
        for decision, action, actor, note in invalid:
            with self.subTest(decision=decision, action=action):
                with self.assertRaises(ForumError):
                    self.store.decide_report(
                        report["id"], decision, actor, content_action=action, note=note
                    )
        self.assertIsNone(self.store.decide_report("0" * 32, "resolved", moderator))
        first = self.store.decide_report(report["id"], "resolved", moderator)
        self.assertIsNotNone(first)
        with closing(sqlite3.connect(self.store.database)) as db:
            before = (
                db.execute("SELECT COUNT(*) FROM forum_moderation_actions").fetchone()[0],
                db.execute("SELECT COUNT(*) FROM forum_notifications").fetchone()[0],
            )
        self.assertIsNone(
            self.store.decide_report(report["id"], "dismissed", moderator,
                                     content_action="delete")
        )
        with closing(sqlite3.connect(self.store.database)) as db:
            after = (
                db.execute("SELECT COUNT(*) FROM forum_moderation_actions").fetchone()[0],
                db.execute("SELECT COUNT(*) FROM forum_notifications").fetchone()[0],
            )
        self.assertEqual(after, before)

    def test_reporter_notifications_have_read_state(self):
        thread = self.store.create_thread(_user(), "Benachrichtigt", "Beitrag")
        reporter_id = "c" * 32
        reporter = _user("Reporter", reporter_id)
        moderator = _user("Mod", "d" * 32)
        first = self.store.create_report(reporter, reason="spam", thread_id=thread["id"])
        second = self.store.create_report(reporter, reason="other", thread_id=thread["id"])
        self.store.decide_report(first["id"], "resolved", moderator)
        self.assertTrue(self.store.resolve_report(
            second["id"], status="dismissed", resolver=moderator
        ))

        notes = self.store.list_notifications(reporter_id)
        self.assertEqual(len(notes), 2)
        self.assertEqual({note["report_id"] for note in notes}, {first["id"], second["id"]})
        self.assertEqual(len(self.store.list_notifications(reporter_id, unread_only=True)), 2)
        newest = notes[0]
        self.assertTrue(self.store.mark_notification_read(newest["id"], reporter_id))
        self.assertFalse(self.store.mark_notification_read("f" * 32, reporter_id))
        self.assertFalse(self.store.mark_notification_read(newest["id"], "b" * 32))
        self.assertEqual(len(self.store.list_notifications(reporter_id, unread_only=True)), 1)
        stored = [note for note in self.store.list_notifications(reporter_id)
                  if note["id"] == newest["id"]][0]
        self.assertIsInstance(stored["read_at"], int)
        self.assertFalse(stored["unread"])
        self.assertTrue(self.store.mark_notification_read(newest["id"], reporter_id))
        with self.assertRaises(ForumError):
            self.store.list_notifications("bad/id")

    def test_list_reports_filters_by_status_and_enriches_payload(self):
        thread = self.store.create_thread(_user(), "Liste", "Beitrag")
        reporter = _user("Reporter", "c" * 32)
        moderator = _user("Mod", "d" * 32)
        reports = {
            reason: self.store.create_report(
                reporter, reason=reason, thread_id=thread["id"]
            )["id"]
            for reason in ("spam", "harassment", "offtopic")
        }
        self.store.decide_report(reports["spam"], "resolved", moderator)
        self.store.decide_report(reports["harassment"], "dismissed", moderator)

        all_reports = self.store.list_reports()
        self.assertEqual({item["id"] for item in all_reports}, set(reports.values()))
        for item in all_reports:
            for key in ("kind", "target_preview", "target_author", "target_permalink",
                        "target_spam_flags", "status", "resolver", "captured_at"):
                self.assertIn(key, item)
        self.assertEqual({item["id"] for item in self.store.list_reports(status="open")},
                         {reports["offtopic"]})
        self.assertEqual({item["id"] for item in self.store.list_reports(status="resolved")},
                         {reports["spam"]})
        self.assertEqual({item["id"] for item in self.store.list_reports(status="dismissed")},
                         {reports["harassment"]})
        self.assertEqual(len(self.store.list_reports(limit=2)), 2)
        with self.assertRaises(ForumError):
            self.store.list_reports(status="unknown")

    def test_legacy_reports_are_migrated_and_duplicates_dismissed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "forum.sqlite3"
            with closing(sqlite3.connect(database)) as db, db:
                db.executescript("""
                    CREATE TABLE threads (
                        thread_id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
                        author_user_id TEXT NOT NULL, author_name TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    );
                    CREATE TABLE replies (
                        reply_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL REFERENCES threads(thread_id),
                        body TEXT NOT NULL, author_user_id TEXT NOT NULL,
                        author_name TEXT NOT NULL, created_at INTEGER NOT NULL
                    );
                    CREATE TABLE forum_reports (
                        report_id TEXT PRIMARY KEY, thread_id TEXT, reply_id TEXT,
                        reason TEXT NOT NULL, created_at INTEGER NOT NULL
                    );
                """)
                db.execute(
                    "INSERT INTO threads(thread_id,title,body,author_user_id,author_name,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    ("a" * 32, "Alt", "Alter Text", "a" * 32, "Autor", 1),
                )
                for report_id, created_at in (("1" * 32, 10), ("2" * 32, 20)):
                    db.execute(
                        "INSERT INTO forum_reports(report_id,thread_id,reason,created_at) "
                        "VALUES(?,?,'spam',?)",
                        (report_id, "a" * 32, created_at),
                    )
            store = ForumStore(directory)
            reports = {item["id"]: item for item in store.list_reports()}
            self.assertEqual(reports["1" * 32]["status"], "open")
            self.assertEqual(reports["2" * 32]["status"], "dismissed")
            self.assertEqual(reports["2" * 32]["resolved_by"], "migration")
            for item in reports.values():
                self.assertEqual(item["target_title"], "Alt")
                self.assertEqual(item["target_body"], "Alter Text")
                self.assertEqual(item["target_author"], "Autor")
            with closing(sqlite3.connect(database)) as db:
                indexes = {row[1] for row in db.execute("PRAGMA index_list(forum_reports)")}
                actions = db.execute(
                    "SELECT action, actor_user_id FROM forum_moderation_actions"
                ).fetchall()
            self.assertIn("reports_open_unique", indexes)
            self.assertIn(("dismissed", "migration"), actions)

    def test_advisory_spam_flags_never_block_posts(self):
        thread = self.store.create_thread(
            _user(), "Werbung", "http://a.example http://b.example http://c.example http://d.example"
        )
        self.assertIn("many_links", thread["spam_flags"])
        reply = self.store.create_reply(_user("Second", "b" * 32), thread["id"], "AAAAAAAAAAAAAAAAAAAAAAAA")
        self.assertIn("repeated_characters", reply["spam_flags"])
        detail = self.store.get_thread(thread["id"])
        self.assertIn("many_links", detail["spam_flags"])
        self.assertIn("repeated_characters", detail["replies"][0]["spam_flags"])

    def test_user_history_lists_visible_posts_from_both_tables(self):
        author = _user("Historian", "e" * 32)
        first = self.store.create_thread(author, "Erstes", "Beitrag eins")
        second = self.store.create_thread(author, "Zweites", "Beitrag zwei")
        reply = self.store.create_reply(author, first["id"], "Antwort")
        history = self.store.list_user_posts("e" * 32)
        self.assertEqual({item["id"] for item in history}, {first["id"], second["id"], reply["id"]})
        self.assertEqual({item["kind"] for item in history}, {"thread", "reply"})
        self.assertTrue(self.store.delete_reply(reply["id"]))
        self.assertNotIn(reply["id"], {item["id"] for item in self.store.list_user_posts("e" * 32)})
        with self.assertRaises(ForumError):
            self.store.list_user_posts("bad/id")


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
        cls._env = patch.dict(os.environ, {"STREAMIOV_FORUM_MODERATORS": ""})
        cls._env.start()
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
        cls.cookie = cls._register("Forum_User")
        _, me = ForumHttpTests._json(cls, "/api/v1/auth/me", cookie=cls.cookie)
        cls.moderator_id = me["user"]["id"]
        cls.other_cookie = cls._register("Forum_Other")
        cls._env.stop()
        cls._env = patch.dict(
            os.environ, {"STREAMIOV_FORUM_MODERATORS": cls.moderator_id}
        )
        cls._env.start()

    @classmethod
    def _register(cls, username):
        body = json.dumps({
            "username": username,
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
        cls._env.stop()
        cls._directory.cleanup()

    def setUp(self):
        self.server.forum_thread_limiter._attempts.clear()
        self.server.forum_reply_limiter._attempts.clear()
        self.server.forum_report_limiter._attempts.clear()
        self.server.forum_moderation_limiter._attempts.clear()

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
        self.assertTrue(status["forum_reports_enabled"])
        self.assertTrue(status["forum_moderation_enabled"])
        self.assertTrue(status["forum_moderation_actions_enabled"])
        self.assertFalse(status["forum_notifications_enabled"])
        self.assertTrue(status["forum_spam_signals_enabled"])
        self.assertTrue(status["forum_history_requires_session"])
        self.assertFalse(status["api_ready"])
        _, me = self._json("/api/v1/auth/me", cookie=self.cookie)
        self.assertTrue(me["user"]["is_forum_moderator"])
        _, other = self._json("/api/v1/auth/me", cookie=self.other_cookie)
        self.assertFalse(other["user"]["is_forum_moderator"])

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

    def test_reports_and_history_require_a_session(self):
        error = self._error("/api/forum/reports", payload={"reason": "spam", "thread_id": "0" * 32},
                            origin=self.origin)
        self.assertEqual(error.code, 401)
        error = self._error("/api/forum/reports", payload={"reason": "spam", "thread_id": "0" * 32},
                            cookie=self.cookie, origin="https://attacker.example")
        self.assertEqual(error.code, 403)
        error = self._error("/api/forum/users/" + "a" * 32 + "/posts", method="GET")
        self.assertEqual(error.code, 401)

    def test_report_resolve_and_history_flow(self):
        _, created = self._json("/api/forum/threads", payload={
            "title": "Meldefluss", "body": "Zu melden",
        }, cookie=self.cookie, origin=self.origin)
        thread_id = created["thread"]["id"]

        error = self._error("/api/forum/reports", payload={"reason": "unknown", "thread_id": thread_id},
                            cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 400)

        status, report = self._json("/api/forum/reports", payload={
            "reason": "spam", "thread_id": thread_id, "detail": "Werbung",
        }, cookie=self.cookie, origin=self.origin)
        self.assertEqual(status, 201)
        self.assertEqual(report["report"]["status"], "open")

        status, queue = self._json("/api/forum/reports", cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertIn(report["report"]["id"], [item["id"] for item in queue["reports"]])

        error = self._error("/api/forum/reports", payload={"reason": "spam", "thread_id": thread_id},
                            cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 409)

        _, me = self._json("/api/v1/auth/me", cookie=self.cookie)
        user_id = me["user"]["id"]
        _, history = self._json("/api/forum/users/" + user_id + "/posts", cookie=self.cookie)
        self.assertIn(thread_id, {item["id"] for item in history["posts"]})

        status, resolved = self._json(
            f"/api/forum/reports/{report['report']['id']}/resolve",
            payload={"status": "resolved"}, cookie=self.cookie, origin=self.origin,
        )
        self.assertEqual(status, 200)
        self.assertEqual(resolved["status"], "resolved")
        open_ids = {item["id"] for item in self.server.forum_store.list_reports(status="open")}
        self.assertNotIn(report["report"]["id"], open_ids)

    def test_moderation_decisions_share_a_rate_limit_across_both_endpoints(self):
        _, created = self._json("/api/forum/threads", payload={
            "title": "Moderationslimit", "body": "Zu melden",
        }, cookie=self.other_cookie, origin=self.origin)
        thread_id = created["thread"]["id"]
        _, report = self._json("/api/forum/reports", payload={
            "reason": "spam", "thread_id": thread_id,
        }, cookie=self.other_cookie, origin=self.origin)
        report_id = report["report"]["id"]

        for index in range(10):
            error = self._error(
                f"/api/forum/reports/{'0' * 32}/decide",
                payload={"decision": "dismissed", "note": f"Prüfung {index}"},
                cookie=self.cookie, origin=self.origin,
            )
            self.assertEqual(error.code, 404)

        error = self._error(
            f"/api/forum/reports/{report_id}/resolve",
            payload={"status": "resolved"}, cookie=self.cookie, origin=self.origin,
        )
        self.assertEqual(error.code, 429)
        self.assertEqual(error.headers["Retry-After"], "600")
        self.assertIn(report_id, {
            item["id"] for item in self.server.forum_store.list_reports(status="open")
        })

    def test_moderation_decision_notifies_reporter_over_http(self):
        _, created = self._json("/api/forum/threads", payload={
            "title": "Meldefluss", "body": "Bitte prüfen",
        }, cookie=self.other_cookie, origin=self.origin)
        thread_id = created["thread"]["id"]
        _, report = self._json("/api/forum/reports", payload={
            "reason": "spam", "thread_id": thread_id, "detail": "Werbung",
        }, cookie=self.other_cookie, origin=self.origin)
        report_id = report["report"]["id"]

        status, open_queue = self._json(
            "/api/forum/reports?status=open&limit=10", cookie=self.cookie
        )
        self.assertEqual(status, 200)
        self.assertEqual(open_queue["status"], "open")
        self.assertIn(report_id, [item["id"] for item in open_queue["reports"]])

        error = self._error(
            f"/api/forum/reports/{report_id}/decide",
            payload={"decision": "resolved", "content_action": "delete", "note": "x"},
            cookie=self.other_cookie, origin=self.origin,
        )
        self.assertEqual(error.code, 403)
        error = self._error(
            f"/api/forum/reports/{report_id}/decide",
            payload={"decision": "unknown"}, cookie=self.cookie, origin=self.origin,
        )
        self.assertEqual(error.code, 400)
        status, locked = self._json(
            f"/api/forum/reports/{report_id}/decide",
            payload={"decision": "resolved", "content_action": "lock"},
            cookie=self.cookie, origin=self.origin,
        )
        self.assertEqual(status, 200)
        self.assertTrue(locked["content_action_applied"])

        error = self._error(
            f"/api/forum/reports/{report_id}/decide",
            payload={"decision": "dismissed", "note": "Erledigt"},
            cookie=self.cookie, origin=self.origin,
        )
        self.assertEqual(error.code, 404)

        status, notes = self._json("/api/forum/notifications", cookie=self.other_cookie)
        self.assertEqual(status, 200)
        own_notes = [item for item in notes["notifications"] if item["report_id"] == report_id]
        self.assertEqual(len(own_notes), 1)
        note = own_notes[0]
        self.assertTrue(note["unread"])
        self.assertIn("gesperrt", note["message"])

        error = self._error(
            f"/api/forum/notifications/{note['id']}/read", cookie=self.cookie, origin=self.origin
        )
        self.assertEqual(error.code, 404)
        error = self._error(
            f"/api/forum/notifications/{note['id']}/read", cookie=self.other_cookie,
            origin="https://attacker.example",
        )
        self.assertEqual(error.code, 403)

        status, marked = self._json(
            f"/api/forum/notifications/{note['id']}/read", method="POST",
            cookie=self.other_cookie, origin=self.origin,
        )
        self.assertEqual(status, 200)
        self.assertEqual(marked["notification_id"], note["id"])
        _, notes = self._json("/api/forum/notifications", cookie=self.other_cookie)
        marked_note = next(
            item for item in notes["notifications"] if item["id"] == note["id"]
        )
        self.assertFalse(marked_note["unread"])

        error = self._error("/api/forum/notifications", method="POST", cookie=self.other_cookie)
        self.assertEqual(error.code, 405)

    def test_moderation_content_action_deletes_the_reported_thread(self):
        _, created = self._json("/api/forum/threads", payload={
            "title": "Spam", "body": "Werbung",
        }, cookie=self.other_cookie, origin=self.origin)
        thread_id = created["thread"]["id"]
        _, report = self._json("/api/forum/reports", payload={
            "reason": "spam", "thread_id": thread_id,
        }, cookie=self.other_cookie, origin=self.origin)
        status, decided = self._json(
            f"/api/forum/reports/{report['report']['id']}/decide",
            payload={"decision": "resolved", "content_action": "delete", "note": "Spam gelöscht"},
            cookie=self.cookie, origin=self.origin,
        )
        self.assertEqual(status, 200)
        self.assertTrue(decided["content_action_applied"])
        self.assertEqual(decided["content_audit"]["action"], "content_delete")
        error = self._error(f"/api/forum/threads/{thread_id}", method="GET")
        self.assertEqual(error.code, 404)

    def test_moderation_queue_requires_a_configured_moderator(self):
        error = self._error("/api/forum/reports", method="GET", cookie=self.other_cookie)
        self.assertEqual(error.code, 403)

        _, created = self._json("/api/forum/threads", payload={
            "title": "Moderation", "body": "Nur Moderatoren dürfen entscheiden.",
        }, cookie=self.cookie, origin=self.origin)
        status, report = self._json("/api/forum/reports", payload={
            "reason": "spam", "thread_id": created["thread"]["id"],
        }, cookie=self.cookie, origin=self.origin)
        self.assertEqual(status, 201)
        error = self._error(
            f"/api/forum/reports/{report['report']['id']}/resolve",
            payload={"status": "resolved"}, cookie=self.other_cookie, origin=self.origin,
        )
        self.assertEqual(error.code, 403)
        self.assertEqual(self.server.forum_store.list_reports(status="open")[0]["status"], "open")

    def test_unsupported_methods_are_rejected(self):
        error = self._error("/api/forum/threads", method="DELETE",
                            cookie=self.cookie, origin=self.origin)
        self.assertEqual(error.code, 405)


class ForumUiContractTests(unittest.TestCase):
    def test_forum_page_matches_the_real_report_and_moderation_api(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "dist" / "streamiov-homepage-worker" / "public" / "forum" / "index.html"
        )
        page = path.read_text(encoding="utf-8")
        for fragment in (
            "reason:reason", "detail:details", "thread_id:targetKind===\"thread\"",
            "reply_id:targetKind===\"reply\"", "is_forum_moderator",
            "id=\"moderation-panel\"", "/api/forum/reports\"",
            "resolveReport(report.id,\"resolved\")",
            "resolveReport(report.id,\"dismissed\")",
        ):
            self.assertIn(fragment, page)
        self.assertNotIn("target_kind", page)
        self.assertNotIn("target_id", page)

    def test_forum_page_wires_inline_reports_notifications_and_moderation(self):
        page = (
            Path(__file__).resolve().parents[1]
            / "dist" / "streamiov-homepage-worker" / "public" / "forum" / "index.html"
        ).read_text(encoding="utf-8")
        for fragment in (
            'id="report-panel"', 'id="report-form"', 'id="report-reason"',
            'id="report-detail"', 'id="notifications-panel"',
            "/api/forum/notifications", "/decide", 'id="report-status-filter"',
            "content_action:contentAction", "target_preview", "target_spam_flags",
            "target_author", "textContent",
        ):
            self.assertIn(fragment, page)
        self.assertNotIn("window.prompt", page)
        self.assertNotIn("innerHTML", page)


class ForumRetentionTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.store = ForumStore(self._directory.name)
        self.author = _user("Author", "a" * 32)
        self.reporter = _user("Reporter", "c" * 32)
        self.moderator = _user("Moderator", "d" * 32)
        self.now = int(time.time())
        self.day = 86_400

    def tearDown(self):
        self._directory.cleanup()

    def _update(self, statement: str, parameters: tuple) -> None:
        with closing(sqlite3.connect(self.store.database)) as db:
            db.execute(statement, parameters)
            db.commit()

    def _seed_retention_records(self):
        visible = self.store.create_thread(self.author, "Sichtbar", "Beitrag")
        old_thread = self.store.create_thread(self.author, "Alt", "Beitrag")
        old_reply = self.store.create_reply(self.author, old_thread["id"], "Antwort")
        cascade_thread = self.store.create_thread(self.author, "Kaskade", "Beitrag")
        self.store.create_reply(self.author, cascade_thread["id"], "Antwort")

        first = self.store.create_report(
            self.reporter, reason="spam", thread_id=visible["id"], detail="Spam",
        )
        second = self.store.create_report(
            self.reporter, reason="harassment", thread_id=visible["id"], detail="Beleidigung",
        )
        opened = self.store.create_report(
            self.reporter, reason="offtopic", thread_id=visible["id"], detail="Offtopic",
        )
        first_decision = self.store.decide_report(first["id"], "resolved", self.moderator)
        second_decision = self.store.decide_report(second["id"], "dismissed", self.moderator)
        first_notification = first_decision["notification"]["notification_id"]
        second_notification = second_decision["notification"]["notification_id"]

        resolved_cutoff = self.now - 120 * self.day
        self._update(
            "UPDATE forum_reports SET created_at=?, resolved_at=? WHERE report_id=?",
            (resolved_cutoff, resolved_cutoff, first["id"]),
        )
        self._update(
            "UPDATE forum_reports SET created_at=?, resolved_at=? WHERE report_id=?",
            (resolved_cutoff, resolved_cutoff, second["id"]),
        )
        self._update(
            "UPDATE forum_reports SET created_at=? WHERE report_id=?",
            (self.now - 120 * self.day, opened["id"]),
        )
        self._update(
            "UPDATE forum_moderation_actions SET created_at=?",
            (self.now - 200 * self.day,),
        )
        self._update(
            "UPDATE forum_notifications SET read_at=? WHERE notification_id=?",
            (self.now - 40 * self.day, first_notification),
        )
        self._update(
            "UPDATE forum_notifications SET created_at=? WHERE notification_id=?",
            (self.now - 120 * self.day, second_notification),
        )
        self._update(
            "UPDATE threads SET created_at=? WHERE thread_id=?",
            (self.now - 200 * self.day, visible["id"]),
        )
        self.assertTrue(self.store.delete_reply(old_reply["id"]))
        self.assertTrue(self.store.delete_thread(old_thread["id"]))
        self.assertTrue(self.store.delete_thread(cascade_thread["id"]))
        old_deleted_at = self.now - 120 * self.day
        self._update(
            "UPDATE replies SET deleted_at=? WHERE reply_id=?",
            (old_deleted_at, old_reply["id"]),
        )
        self._update(
            "UPDATE threads SET deleted_at=? WHERE thread_id IN (?, ?)",
            (old_deleted_at, old_thread["id"], cascade_thread["id"]),
        )
        return visible, opened

    def test_status_is_a_dry_run_and_apply_removes_only_expired_records(self):
        visible, opened = self._seed_retention_records()
        status = self.store.retention_status(now=self.now)
        self.assertTrue(status["dry_run"])
        self.assertFalse(status["policy"]["email_notifications"])
        self.assertEqual(status["eligible"], {
            "resolved_reports": 2,
            "moderation_actions": 2,
            "read_notifications": 1,
            "unread_notifications": 1,
            "deleted_replies": 2,
            "deleted_threads": 2,
        })
        self.assertEqual(len(self.store.list_reports(status="all")), 3)

        report = self.store.apply_retention(now=self.now)
        self.assertFalse(report["dry_run"])
        self.assertEqual(report["eligible"], status["eligible"])
        self.assertEqual(report["deleted"], status["eligible"])
        self.assertEqual(
            [item["id"] for item in self.store.list_reports(status="all")],
            [opened["id"]],
        )
        self.assertEqual(self.store.list_notifications(self.reporter.user_id), [])
        self.assertIsNotNone(self.store.get_thread(visible["id"]))
        with closing(sqlite3.connect(self.store.database)) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM forum_moderation_actions"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM replies"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM threads WHERE deleted = 1"
            ).fetchone()[0], 0)

        second = self.store.apply_retention(now=self.now)
        self.assertTrue(all(count == 0 for count in second["eligible"].values()))
        self.assertTrue(all(count == 0 for count in second["deleted"].values()))

    def test_legacy_soft_deletes_receive_a_deletion_timestamp(self):
        thread = self.store.create_thread(self.author, "Alt", "Beitrag")
        reply = self.store.create_reply(self.author, thread["id"], "Antwort")
        with closing(sqlite3.connect(self.store.database)) as db:
            db.execute("ALTER TABLE threads DROP COLUMN deleted_at")
            db.execute("ALTER TABLE replies DROP COLUMN deleted_at")
            db.execute("UPDATE threads SET deleted = 1 WHERE thread_id=?", (thread["id"],))
            db.execute("UPDATE replies SET deleted = 1 WHERE reply_id=?", (reply["id"],))
            db.commit()

        migrated = ForumStore(self._directory.name)
        with closing(sqlite3.connect(migrated.database)) as db:
            thread_row = db.execute(
                "SELECT created_at, deleted_at FROM threads WHERE thread_id=?", (thread["id"],)
            ).fetchone()
            reply_row = db.execute(
                "SELECT created_at, deleted_at FROM replies WHERE reply_id=?", (reply["id"],)
            ).fetchone()
        self.assertEqual(thread_row[1], thread_row[0])
        self.assertEqual(reply_row[1], reply_row[0])


class ForumCliTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.store = ForumStore(self._directory.name)
        self.author = _user("Author", "a" * 32)
        self.reporter = _user("Reporter", "c" * 32)
        self.thread = self.store.create_thread(
            self.author, "Werbung",
            "http://a.example http://b.example http://c.example http://d.example",
        )
        self.report = self.store.create_report(
            self.reporter, reason="spam", thread_id=self.thread["id"], detail="Werbung",
        )

    def tearDown(self):
        self._directory.cleanup()

    def _run(self, *arguments):
        output = StringIO()
        with redirect_stdout(output):
            result = main(["--data-dir", self._directory.name, *arguments])
        self.assertEqual(result, 0)
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_report_and_spam_cli_output(self):
        reports = self._run("--forum-reports")
        self.assertEqual(reports[0]["id"], self.report["id"])
        self.assertEqual(reports[0]["status"], "open")
        spam = self._run("--forum-spam")
        self.assertTrue(any(
            item["id"] == self.thread["id"] and "many_links" in item["spam_flags"]
            for item in spam
        ))

    def test_resolve_and_history_cli_output(self):
        self._run("--forum-resolve-report", self.report["id"], "dismissed")
        reports = self._run("--forum-reports")
        self.assertEqual(reports[0]["status"], "dismissed")
        self.assertEqual(reports[0]["resolved_by"], "cli-operator")
        posts = self._run("--forum-history", "a" * 32)
        self.assertIn(self.thread["id"], [post["id"] for post in posts])
        with self.assertRaises(SystemExit):
            self._run("--forum-resolve-report", self.report["id"], "resolved")

    def test_decide_and_notifications_cli_output(self):
        decided = self._run(
            "--forum-decide-report", self.report["id"], "resolved",
            "--forum-content-action", "none", "--forum-note", "Geprüft",
        )[0]
        self.assertTrue(decided["ok"])
        self.assertEqual(decided["audit"]["actor_user_id"], "cli-operator")
        self.assertIsNotNone(decided["notification"])
        notification_id = decided["notification"]["notification_id"]
        notes = self._run("--forum-notifications", "c" * 32)
        self.assertEqual(notes[0]["id"], notification_id)
        self.assertTrue(notes[0]["unread"])
        self._run("--forum-mark-notification-read", notification_id, "c" * 32)
        notes = self._run("--forum-notifications", "c" * 32)
        self.assertFalse(notes[0]["unread"])

    def test_content_action_flags_require_a_decision(self):
        with self.assertRaises(SystemExit):
            self._run("--forum-note", "Geprüft")
        with self.assertRaises(SystemExit):
            self._run("--forum-content-action", "lock")

    def test_retention_cli_reports_policy_and_runs(self):
        status = self._run("--forum-retention-status")[0]
        self.assertTrue(status["dry_run"])
        self.assertIn("resolved_reports", status["eligible"])
        self.assertEqual(status["policy"]["visible_threads_and_replies"], "kept")

        applied = self._run("--forum-retention-run")[0]
        self.assertFalse(applied["dry_run"])
        self.assertEqual(applied["deleted"], applied["eligible"])
        with self.assertRaises(SystemExit):
            self._run("--forum-retention-status", "--forum-retention-run")


if __name__ == "__main__":
    unittest.main()
