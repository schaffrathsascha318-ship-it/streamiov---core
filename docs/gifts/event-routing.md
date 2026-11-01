# STREAMIOV-native gift event routing

`ai.runtime.gift_event_router.GiftEventRouter` is a small in-process security boundary for gift effects.

- Only signed `STREAMIOV_NATIVE` events are accepted. TikTok-native events are rejected and must use a separate officially permitted integration.
- Every event is bound to one active STREAMIOV session and its exact streamer recipient.
- The gift-to-effect mapping is supplied only from the released-gift configuration; unknown or unreleased gifts cannot dispatch.
- HMAC-SHA256 signatures, short event expiry, bounded TTL, unique event IDs and nonces protect against tampering and replay.
- Handlers are registered by trusted code. The event cannot supply executable code or arbitrary action names.
- Event IDs/nonces are consumed before handler execution, so a failed handler cannot be replayed into a duplicate effect.
- The handler receives a sanitized event without signature or nonce.

This is an integration-ready routing primitive, not a network endpoint or production gallery integration. It does not process payments, perform payouts, or claim TikTok event access. The current three-gift neon pack is still `REVIEW_REQUIRED`, so it is intentionally not configured as a released gift and cannot be sent through this router yet.

Run `python -m unittest tests.test_gift_event_router -v`.
