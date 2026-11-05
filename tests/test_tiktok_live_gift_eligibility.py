import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from host.tiktok_live_gift_eligibility import TikTokLiveGiftEligibility, SCOPE


NOW = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
CLAIM = {"creator_id": "creator-123", "verified": True,
         "source": "tiktok_verified_account", "country_code": "DE"}


class TikTokLiveGiftEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gate = TikTokLiveGiftEligibility(Path(self.tmp.name) / "gate.sqlite3")

    def approve(self, **kwargs):
        self.gate.set_approval(country_code="DE", evidence_ref="ticket:written-tiktok-approval",
                               confirmed_at="2026-11-05T12:00:00Z", now=NOW, **kwargs)

    def test_default_deny_when_no_country_approval_exists(self):
        decision = self.gate.evaluate(CLAIM, now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "country_not_approved")

    def test_explicit_approval_for_exact_scope_allows_verified_creator(self):
        self.approve()
        decision = self.gate.evaluate(CLAIM, now=NOW)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.scope, SCOPE)

    def test_unverified_or_ip_derived_country_is_denied(self):
        self.approve()
        claim = dict(CLAIM, verified=False)
        self.assertFalse(self.gate.evaluate(claim, now=NOW).allowed)
        claim = dict(CLAIM, source="ip_geolocation")
        self.assertFalse(self.gate.evaluate(claim, now=NOW).allowed)

    def test_expired_approval_is_denied(self):
        self.approve(expires_at="2026-11-05T23:59:59Z")
        decision = self.gate.evaluate(CLAIM, now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "approval_expired")

    def test_revocation_is_denied_and_audited(self):
        self.approve()
        self.gate.revoke("DE", evidence_ref="ticket:revocation", now=NOW)
        self.assertFalse(self.gate.evaluate(CLAIM, now=NOW).allowed)
        self.assertEqual(len(self.gate.audit_log("DE")), 2)

    def test_wrong_scope_and_invalid_country_are_rejected(self):
        with self.assertRaises(ValueError):
            self.gate.set_approval(country_code="DE", evidence_ref="x",
                                   confirmed_at="2026-11-05T12:00:00Z",
                                   scope="tiktok_mini_app_iap", now=NOW)
        with self.assertRaises(ValueError):
            self.gate.set_approval(country_code="XX", evidence_ref="x",
                                   confirmed_at="2026-11-05T12:00:00Z", now=NOW)


if __name__ == "__main__":
    unittest.main()
