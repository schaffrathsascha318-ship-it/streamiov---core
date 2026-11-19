"""Authenticated, idempotent routing for STREAMIOV-native gift effects.

The router only forwards approved native-gift effects to an active STREAMIOV
session. It never handles TikTok-native gifts, money, checkout or payouts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SIGNED_FIELDS = (
    "event_id", "source", "session_id", "recipient_id", "gift_id",
    "effect_id", "created_at", "expires_at", "nonce",
)
MAX_EVENT_TTL_SECONDS = 300
MAX_EVENT_AGE_SECONDS = 120
MAX_FUTURE_SKEW_SECONDS = 30
MAX_SEEN_EVENTS = 20_000


def _canonical_payload(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        {key: payload.get(key) for key in SIGNED_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_native_gift_event(payload: Mapping[str, Any], secret: bytes) -> str:
    """Create a SHA-256 HMAC for a trusted server-side event producer."""
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("Gift event signing secret must contain at least 32 bytes.")
    return hmac.new(secret, _canonical_payload(payload), hashlib.sha256).hexdigest()


class GiftEventRouter:
    def __init__(
        self,
        *,
        signing_secret: bytes,
        released_gift_effects: Mapping[str, str],
        max_seen_events: int = MAX_SEEN_EVENTS,
    ) -> None:
        if not isinstance(signing_secret, bytes) or len(signing_secret) < 32:
            raise ValueError("Gift event signing secret must contain at least 32 bytes.")
        if not 1 <= max_seen_events <= MAX_SEEN_EVENTS:
            raise ValueError("max_seen_events is outside the supported range.")
        self._secret = signing_secret
        self._gift_effects = dict(released_gift_effects)
        self._sessions: dict[str, str] = {}
        self._handlers: dict[str, Callable[[dict], Any]] = {}
        self._seen_events: dict[str, int] = {}
        self._seen_nonces: dict[str, int] = {}
        self._max_seen = max_seen_events
        self._lock = threading.Lock()

    def open_session(self, session_id: str, streamer_id: str) -> None:
        if not self._valid_id(session_id) or not self._valid_id(streamer_id):
            raise ValueError("Session and streamer identifiers are required.")
        with self._lock:
            self._sessions[session_id] = streamer_id

    def close_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def register_effect_handler(self, effect_id: str, handler: Callable[[dict], Any]) -> None:
        if not self._valid_id(effect_id) or not callable(handler):
            raise ValueError("A valid effect ID and callable handler are required.")
        with self._lock:
            self._handlers[effect_id] = handler

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))

    def _reject(self, reason: str) -> dict:
        return {"accepted": False, "reason": reason, "effect_dispatched": False}

    def _prune(self, now: int) -> None:
        self._seen_events = {
            key: expiry for key, expiry in self._seen_events.items() if expiry >= now
        }
        self._seen_nonces = {
            key: expiry for key, expiry in self._seen_nonces.items() if expiry >= now
        }

    def dispatch(self, payload: Mapping[str, Any], *, now: int | None = None) -> dict:
        if not isinstance(payload, Mapping):
            return self._reject("invalid_event")
        if payload.get("source") != "STREAMIOV_NATIVE":
            return self._reject("source_not_supported")
        for field in ("event_id", "session_id", "recipient_id", "gift_id", "effect_id", "nonce"):
            if not self._valid_id(payload.get(field)):
                return self._reject("invalid_event_identifier")
        created_at = payload.get("created_at")
        expires_at = payload.get("expires_at")
        if isinstance(created_at, bool) or not isinstance(created_at, int):
            return self._reject("invalid_timestamp")
        if isinstance(expires_at, bool) or not isinstance(expires_at, int):
            return self._reject("invalid_timestamp")
        current = int(time.time()) if now is None else now
        if isinstance(current, bool) or not isinstance(current, int):
            return self._reject("invalid_clock")
        if created_at > current + MAX_FUTURE_SKEW_SECONDS:
            return self._reject("event_from_future")
        if created_at < current - MAX_EVENT_AGE_SECONDS or expires_at < current:
            return self._reject("event_expired")
        if expires_at <= created_at or expires_at > created_at + MAX_EVENT_TTL_SECONDS:
            return self._reject("invalid_event_ttl")

        supplied_signature = payload.get("signature")
        if not isinstance(supplied_signature, str):
            return self._reject("signature_missing")
        expected = sign_native_gift_event(payload, self._secret)
        if not hmac.compare_digest(expected, supplied_signature):
            return self._reject("signature_invalid")

        with self._lock:
            self._prune(current)
            if payload["event_id"] in self._seen_events:
                return self._reject("duplicate_event")
            if payload["nonce"] in self._seen_nonces:
                return self._reject("replayed_nonce")
            if len(self._seen_events) >= self._max_seen:
                return self._reject("dedupe_capacity_reached")

            expected_effect = self._gift_effects.get(payload["gift_id"])
            if expected_effect is None:
                return self._reject("gift_not_released")
            if expected_effect != payload["effect_id"]:
                return self._reject("gift_effect_mismatch")
            if self._sessions.get(payload["session_id"]) != payload["recipient_id"]:
                return self._reject("recipient_session_mismatch")
            handler = self._handlers.get(payload["effect_id"])
            if handler is None:
                return self._reject("effect_handler_unavailable")

            # Consume event ID and nonce before invoking user/runtime code so a
            # throwing handler cannot make a replay execute the effect twice.
            self._seen_events[payload["event_id"]] = expires_at
            self._seen_nonces[payload["nonce"]] = expires_at

        safe_event = {
            "event_id": payload["event_id"],
            "source": "STREAMIOV_NATIVE",
            "session_id": payload["session_id"],
            "recipient_id": payload["recipient_id"],
            "gift_id": payload["gift_id"],
            "effect_id": payload["effect_id"],
            "created_at": created_at,
            "expires_at": expires_at,
        }
        try:
            result = handler(safe_event)
        except Exception:
            return self._reject("effect_handler_failed")
        if result is False:
            return self._reject("effect_handler_rejected")
        return {
            "accepted": True,
            "reason": "dispatched",
            "effect_dispatched": True,
            "event_id": payload["event_id"],
            "session_id": payload["session_id"],
        }
