import unittest

from ai.runtime.gift_event_router import (
    GiftEventRouter,
    sign_native_gift_event,
)


SECRET = b"streamiov-test-secret-that-is-at-least-32-bytes-long"


def make_event(**changes):
    event = {
        "event_id": "event-001",
        "source": "STREAMIOV_NATIVE",
        "session_id": "session-1",
        "recipient_id": "streamer-1",
        "gift_id": "neon-heart",
        "effect_id": "neon-heart-pulse",
        "created_at": 1000,
        "expires_at": 1120,
        "nonce": "nonce-001",
    }
    event.update(changes)
    event["signature"] = sign_native_gift_event(event, SECRET)
    return event


class GiftEventRouterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.router = GiftEventRouter(
            signing_secret=SECRET,
            released_gift_effects={"neon-heart": "neon-heart-pulse"},
        )
        self.router.open_session("session-1", "streamer-1")
        self.router.register_effect_handler(
            "neon-heart-pulse", lambda event: self.calls.append(event) or True
        )

    def test_dispatches_signed_native_gift_to_exact_active_session(self):
        result = self.router.dispatch(make_event(), now=1050)
        self.assertTrue(result["accepted"])
        self.assertTrue(result["effect_dispatched"])
        self.assertEqual(result["session_id"], "session-1")
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("signature", self.calls[0])
        self.assertNotIn("nonce", self.calls[0])

    def test_duplicate_event_and_replayed_nonce_are_rejected(self):
        event = make_event()
        self.assertTrue(self.router.dispatch(event, now=1050)["accepted"])
        self.assertEqual(self.router.dispatch(event, now=1050)["reason"], "duplicate_event")
        second = make_event(event_id="event-002")
        self.assertEqual(self.router.dispatch(second, now=1050)["reason"], "replayed_nonce")
        self.assertEqual(len(self.calls), 1)

    def test_tiktok_events_and_unreleased_gifts_are_rejected(self):
        self.assertEqual(
            self.router.dispatch(make_event(source="TIKTOK_NATIVE"), now=1050)["reason"],
            "source_not_supported",
        )
        unknown = make_event(event_id="event-003", gift_id="not-released", nonce="nonce-003")
        self.assertEqual(self.router.dispatch(unknown, now=1050)["reason"], "gift_not_released")
        self.assertEqual(self.calls, [])

    def test_invalid_signature_expiry_and_ttl_are_rejected(self):
        bad_signature = make_event()
        bad_signature["signature"] = "0" * 64
        self.assertEqual(self.router.dispatch(bad_signature, now=1050)["reason"], "signature_invalid")
        self.assertEqual(self.router.dispatch(make_event(event_id="old", nonce="old-nonce"), now=1300)["reason"], "event_expired")
        long_ttl = make_event(event_id="long", nonce="long-nonce", expires_at=1500)
        self.assertEqual(self.router.dispatch(long_ttl, now=1050)["reason"], "invalid_event_ttl")

    def test_wrong_recipient_and_effect_handler_failures_are_safe(self):
        wrong_recipient = make_event(event_id="wrong", nonce="wrong-nonce", recipient_id="other")
        self.assertEqual(self.router.dispatch(wrong_recipient, now=1050)["reason"], "recipient_session_mismatch")

        self.router.register_effect_handler("neon-heart-pulse", lambda _event: (_ for _ in ()).throw(RuntimeError("secret")))
        failed = make_event(event_id="failed", nonce="failed-nonce")
        self.assertEqual(self.router.dispatch(failed, now=1050)["reason"], "effect_handler_failed")
        self.assertEqual(self.router.dispatch(failed, now=1050)["reason"], "duplicate_event")

    def test_closed_session_cannot_receive_gift_effect(self):
        self.router.close_session("session-1")
        event = make_event()
        self.assertEqual(self.router.dispatch(event, now=1050)["reason"], "recipient_session_mismatch")


if __name__ == "__main__":
    unittest.main()
