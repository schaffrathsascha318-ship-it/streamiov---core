"""Tests for the versioned local event ledger."""
import tempfile
import unittest
import uuid
from pathlib import Path

from host.event_store import (
    EVENT_SCHEMA_VERSION,
    EventStore,
    EventValidationError,
    normalise_data,
    validate_event,
)


def make_event(event_id=None, **overrides):
    payload = {
        "event_id": str(event_id or uuid.uuid4()),
        "schema_version": EVENT_SCHEMA_VERSION,
        "source": "studio",
        "type": "studio.scene.take",
        "severity": "info",
        "occurred_at": "2026-11-26T12:00:00Z",
        "data": {"scene": "LIVE"},
    }
    payload.update(overrides)
    return payload


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self._directory.name))

    def tearDown(self):
        self._directory.cleanup()

    def test_event_validation_rejects_unknown_or_malformed_fields(self):
        for event in (
            {**make_event(), "source": "renderer"},
            {**make_event(), "type": "platform.gift.fake"},
            {**make_event(), "severity": "success"},
            {**make_event(), "schema_version": 2},
            {**make_event(), "occurred_at": "2026-11-26 12:00:00"},
            {**make_event(), "extra": 1},
            {**make_event(), "event_id": "not-a-uuid"},
        ):
            with self.subTest(event=event):
                with self.assertRaises(EventValidationError):
                    validate_event(event)

    def test_data_is_flat_bounded_and_redacted(self):
        cleaned = normalise_data({
            "scene": "  LIVE  ",
            "streamKey": "abc123",
            "rtmp": "rtmps://live.example/app/key",
            "ok": True,
            "count": 3,
        })
        self.assertEqual(cleaned["scene"], "LIVE")
        self.assertEqual(cleaned["streamKey"], "[REDACTED]")
        self.assertEqual(cleaned["rtmp"], "[REDACTED]")
        self.assertTrue(cleaned["ok"])
        self.assertEqual(cleaned["count"], 3)
        with self.assertRaises(EventValidationError):
            normalise_data({"nested": {"secret": "x"}})
        with self.assertRaises(EventValidationError):
            normalise_data({f"field{n}": "x" for n in range(31)})

    def test_local_gift_effect_preview_event_is_accepted(self):
        event = make_event(
            type="studio.gift.effect_preview",
            data={
                "template_id": "rose",
                "template_name": "Rose",
                "effect_id": "heart",
                "effect_symbol": "♥",
                "local_points": 1,
            },
        )
        stored, created = self.store.publish("owner", event)
        self.assertTrue(created)
        self.assertEqual(stored["type"], "studio.gift.effect_preview")
        self.assertEqual(stored["data"]["template_id"], "rose")
        self.assertEqual(stored["data"]["effect_id"], "heart")
        self.assertEqual(stored["data"]["local_points"], 1)

    def test_local_game_analysis_events_are_accepted(self):
        event = make_event(
            type="studio.gameplay.observation",
            data={"game": "Neon Relay", "kind": "objective", "detail": "Punkt erobert"},
        )
        stored, created = self.store.publish("owner", event)
        self.assertTrue(created)
        self.assertEqual(stored["type"], "studio.gameplay.observation")
        self.assertEqual(stored["data"]["game"], "Neon Relay")
        with self.assertRaises(EventValidationError):
            self.store.publish("owner", make_event(type="studio.game.opened", data={"game": "Neon Relay"}))

    def test_publish_is_idempotent_and_owner_scoped(self):
        event = make_event()
        stored, created = self.store.publish("owner", event)
        self.assertTrue(created)
        self.assertEqual(stored["event_id"], event["event_id"])
        self.assertEqual(stored["data"], {"scene": "LIVE"})
        again, created_again = self.store.publish("owner", event)
        self.assertFalse(created_again)
        self.assertEqual(again["event_id"], event["event_id"])
        self.assertEqual(self.store.count("owner"), 1)

        restarted = EventStore(Path(self._directory.name))
        self.assertEqual(restarted.count("owner"), 1)
        self.assertEqual(restarted.list("owner")[0]["event_id"], event["event_id"])
        self.assertEqual(restarted.list("other"), [])

    def test_list_is_bounded_and_newest_first(self):
        older = make_event()
        newer = make_event()
        self.store.publish("owner", older)
        self.store.publish("owner", newer)
        events = self.store.list("owner", limit=1)
        self.assertEqual([event["event_id"] for event in events], [newer["event_id"]])
        self.assertEqual(len(self.store.list("owner", limit=999)), 2)
        with self.assertRaises(EventValidationError):
            self.store.publish("", make_event())
        with self.assertRaises(EventValidationError):
            self.store.list("")


if __name__ == "__main__":
    unittest.main()
