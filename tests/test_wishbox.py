"""Tests for the durable Wunschbox music and game order centre."""
import tempfile
import unittest
from pathlib import Path

from host.wishbox import WishboxError, WishboxStore, classify


class FakeMusicCatalog:
    def __init__(self, tracks=None, *, error=None):
        self.tracks = tracks if tracks is not None else [{
            "id": "trk-1", "title": "Neon Nights", "artist": "StreamioV Band",
            "allowed": True, "state": "allowed", "reasons": [],
        }]
        self.error = error

    def gate(self, territory, usage):
        if self.error:
            raise ValueError(self.error)
        return {"tracks": self.tracks if usage == "live_stream" else []}


class WishboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.events = []
        self.store = WishboxStore(
            self.root, music_catalog=FakeMusicCatalog(),
            event_publisher=lambda user, kind, data: self.events.append((user, kind, data)),
        )

    def tearDown(self):
        self.directory.cleanup()

    def submit(self, text, **kwargs):
        return self.store.submit("viewer-1", text, **kwargs)

    def test_music_order_uses_live_approved_catalogue_and_tracks_history(self):
        order = self.submit("Spiele Neon Nights von StreamioV Band")
        self.assertEqual(order["status"], "queued")
        self.assertEqual(order["kind"], "music")
        self.assertEqual(order["agent"], "music")
        self.assertEqual(order["handoff"]["track_id"], "trk-1")
        detail = self.store.detail(order["id"], "viewer-1")
        self.assertEqual([entry["to"] for entry in detail["history"]],
                         ["received", "reviewed", "queued"])
        self.assertTrue(detail["feedback"])

    def test_music_without_rights_is_rejected_and_not_dispatched(self):
        order = self.submit("Song fremder Titel von Unbekannt")
        self.assertEqual(order["status"], "rejected")
        self.assertEqual(order["agent"], "")
        self.assertIn("Rechte", order["feedback"])
        with self.assertRaises(WishboxError):
            self.store.dispatch(order["id"], "viewer-1")

    def test_missing_catalogue_fails_closed(self):
        store = WishboxStore(self.root / "empty", music_catalog=FakeMusicCatalog(error="no_catalogue"))
        order = store.submit("viewer-1", "Spiele Neon Nights von StreamioV Band")
        self.assertEqual(order["status"], "rejected")

    def test_duplicate_music_wish_is_detected(self):
        first = self.submit("Spiele Neon Nights von StreamioV Band", sender="alice")
        second = self.submit("Spiele Neon Nights von StreamioV Band", sender="bob")
        self.assertEqual(second["id"], first["id"])
        self.assertTrue(second["duplicate"])

    def test_game_order_is_handed_to_gaming_agent_with_safety_constraints(self):
        order = self.submit("Kannst du eine Challenge in Neon Relay analysieren?")
        self.assertEqual(order["kind"], "game")
        self.assertEqual(order["game"], "neon-relay")
        self.assertEqual(order["intent"], "analysis")
        self.assertEqual(order["status"], "queued")
        self.assertEqual(order["agent"], "gaming")
        self.assertEqual(order["handoff"]["agent"], "gaming")
        self.assertIn("no_game_input", order["handoff"]["constraints"])
        self.assertIn("streamer_control", order["handoff"]["constraints"])

    def test_game_order_lifecycle_reaches_completed_result(self):
        order = self.submit("Analysiere meine Situation in Echo Grid")
        assigned = self.store.dispatch(order["id"], "viewer-1")
        self.assertEqual(assigned["status"], "assigned")
        running = self.store.claim(order["id"], "viewer-1", agent="gaming-ki")
        self.assertEqual(running["status"], "in_progress")
        self.assertEqual(running["agent"], "gaming-ki")
        done = self.store.complete(order["id"], "viewer-1", "Tempo zu hoch, Deckung nutzen.")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"], "Tempo zu hoch, Deckung nutzen.")
        detail = self.store.detail(order["id"], "viewer-1")
        self.assertEqual([entry["to"] for entry in detail["history"]][-3:],
                         ["assigned", "in_progress", "completed"])

    def test_cheat_and_automation_requests_are_rejected(self):
        for text in ("Nutze einen Aimbot inValorant", "Aktiviere ein Mod Menu in Minecraft",
                     "Spiele mit Auto-Klick in Fortnite"):
            with self.subTest(text=text):
                order = self.submit(text)
                self.assertEqual(order["status"], "rejected")
                self.assertFalse(order["handoff"])

    def test_unknown_game_requires_clarification_then_requeues(self):
        order = self.submit("Mach mal eine Herausforderung")
        self.assertEqual(order["status"], "clarification_needed")
        clarified = self.store.clarify(order["id"], "viewer-1", "In Pulse Defender bitte.")
        self.assertEqual(clarified["game"], "pulse-defender")
        self.assertEqual(clarified["status"], "queued")
        self.assertIn("wishbox.order.status", [event[1] for event in self.events[2:]])

    def test_streamer_can_reject_a_queued_order(self):
        order = self.submit("Spiele Neon Nights von StreamioV Band")
        rejected = self.store.reject(order["id"], "viewer-1", "Nicht jetzt")
        self.assertEqual(rejected["status"], "rejected")
        self.assertNotIn(rejected["id"],
                         [item["id"] for item in self.store.handoffs("viewer-1")])

    def test_owner_scoping_and_id_validation(self):
        order = self.submit("Analysiere Neon Relay")
        self.assertIsNone(self.store.detail(order["id"], "another-user"))
        with self.assertRaises(WishboxError):
            self.store.dispatch("../etc/passwd", "viewer-1")
        with self.assertRaises(WishboxError):
            self.store.submit("viewer-1", "x")
        self.assertEqual(self.store.list_orders("another-user"), [])

    def test_handoffs_only_contain_pending_game_orders(self):
        game = self.submit("Challenge in Neon Relay")
        music = self.submit("Spiele Neon Nights von StreamioV Band")
        self.store.dispatch(game["id"], "viewer-1")
        self.store.dispatch(music["id"], "viewer-1")
        pending = self.store.handoffs("viewer-1")
        self.assertEqual([item["id"] for item in pending], [game["id"]])

    def test_events_carry_no_secret_values(self):
        order = self.submit("Analysiere Echo Grid", sender="rtmps://secret.example/live/key")
        self.assertTrue(self.events)
        self.assertNotIn("secret.example", str(self.events))
        self.assertEqual(order["sender"], "rtmps://secret.example/live/key")
        self.assertEqual([event[1] for event in self.events],
                         ["wishbox.order.received", "wishbox.order.status"])

    def test_failing_event_publisher_cannot_undo_committed_order(self):
        def broken_publisher(_user, _kind, _data):
            raise RuntimeError("ledger offline")

        store = WishboxStore(
            self.root / "broken-ledger", music_catalog=FakeMusicCatalog(),
            event_publisher=broken_publisher,
        )
        order = store.submit("viewer-2", "Analysiere Echo Grid")
        self.assertEqual(order["status"], "queued")
        self.assertEqual(store.detail(order["id"], "viewer-2")["status"], "queued")

    def test_classifier_distinguishes_music_from_game_wording(self):
        self.assertEqual(classify("Spiele mir das Lied Neon Nights")["kind"], "music")
        self.assertEqual(classify("Spiele eine Runde Neon Relay")["kind"], "game")
        self.assertEqual(classify("Was ist deine Meinung?")["kind"], "unknown")


if __name__ == "__main__":
    unittest.main()
