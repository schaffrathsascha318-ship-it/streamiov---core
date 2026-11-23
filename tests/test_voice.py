from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from host.voice import VoiceError, VoiceRoomStore


class VoiceRoomStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = VoiceRoomStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_room_owner_invite_and_member_scoped_token(self):
        with patch.dict(os.environ, {"STREAMIOV_VOICE_SIGNING_KEY": "v" * 48}):
            room = self.store.create_room("owner-id", "Team Voice")
            joined = self.store.join("guest-id", room["invite_code"])
            self.assertEqual(joined["room_id"], room["room_id"])
            self.assertEqual(joined["role"], "guest")
            token = self.store.issue_member_token("guest-id", room["room_id"])
            self.assertEqual(token["role"], "guest")
            self.assertEqual(token["expires_in"], 300)
            header, claims, signature = token["token"].split(".")
            payload = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
            self.assertEqual(payload["sub"], "guest-id")
            self.assertEqual(payload["room"], room["room_id"])
            signed = (header + "." + claims).encode("ascii")
            expected = hmac.new(b"v" * 48, signed, hashlib.sha256).digest()
            actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            self.assertTrue(hmac.compare_digest(actual, expected))

    def test_invite_is_single_use_and_membership_is_required(self):
        room = self.store.create_room("owner-id", "Team")
        invite = self.store.create_invite("owner-id", room["room_id"], max_uses=1)
        self.store.join("member-id", invite["invite_code"])
        with self.assertRaises(VoiceError):
            self.store.join("other-id", invite["invite_code"])
        with self.assertRaises(VoiceError):
            self.store.issue_member_token("outsider-id", room["room_id"])

    def test_expired_invite_and_closed_room_are_rejected(self):
        room = self.store.create_room("owner-id", "Team", now=1000)
        invite = self.store.create_invite("owner-id", room["room_id"], ttl=60, now=1000)
        with self.assertRaises(VoiceError):
            self.store.join("guest-id", invite["invite_code"], now=1060)
        self.assertTrue(self.store.close_room("owner-id", room["room_id"], now=1100))
        with self.assertRaises(VoiceError):
            self.store.issue_member_token("owner-id", room["room_id"])

    def test_owner_cannot_be_demoted_by_using_guest_invite(self):
        room = self.store.create_room("owner-id", "Team")
        self.assertEqual(self.store.join("owner-id", room["invite_code"])["role"], "owner")
        self.assertEqual(self.store.role_for("owner-id", room["room_id"]), "owner")

    def test_boolean_invite_limits_are_rejected(self):
        room = self.store.create_room("owner-id", "Team")
        with self.assertRaises(VoiceError):
            self.store.create_invite("owner-id", room["room_id"], ttl=True)
        with self.assertRaises(VoiceError):
            self.store.create_invite("owner-id", room["room_id"], max_uses=True)


if __name__ == "__main__":
    unittest.main()
