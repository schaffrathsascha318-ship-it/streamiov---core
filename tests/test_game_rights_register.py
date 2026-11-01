import tempfile
import unittest
from pathlib import Path
from ai.rights import RightsRegister, RightsError


class RightsRegisterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = RightsRegister(Path(self.tmp.name) / "rights.sqlite3")
        self.r.create_title("retro-001", "Example Retro Game", "DE")
        self.r.add_component("code", "retro-001", "software", "Game code")
        self.r.add_component("music", "retro-001", "recording", "Soundtrack")
        self.r.add_evidence("code", "https://www.gesetze-im-internet.de/urhg/__64.html",
                            "Official legislation portal", "2026-10-31",
                            "Copyright term provision reviewed")
    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_assessment_blocks(self):
        result = self.r.release_decision("retro-001", "remaster")
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertIn("assessment_missing", [x["reason"] for x in result["blockers"]])

    def test_ended_commercial_license_does_not_clear(self):
        self.r.assess("code", "remaster", "LICENSE_REQUIRED",
                      "Commercial licence ended; copyright not established.",
                      "game-rights-agent", human_review_required=False)
        result = self.r.release_decision("retro-001", "remaster")
        self.assertIn("LICENSE_REQUIRED", [x["reason"] for x in result["blockers"]])

    def test_positive_status_requires_evidence(self):
        with self.assertRaises(RightsError):
            self.r.assess("music", "distribution", "CLEARED",
                          "No source recorded", "game-rights-agent")

    def test_positive_status_still_requires_human_review_by_default(self):
        self.r.assess("code", "remaster", "PUBLIC_DOMAIN_VERIFIED",
                      "Verified only for Germany", "game-rights-agent")
        result = self.r.release_decision("retro-001", "remaster")
        self.assertIn("human_review_required", [x["reason"] for x in result["blockers"]])

    def test_clearance_is_activity_specific(self):
        self.r.assess("code", "preservation", "CLEARED",
                      "Permission limited to preservation", "reviewer",
                      human_review_required=False)
        result = self.r.release_decision("retro-001", "remaster")
        self.assertIn("assessment_missing", [x["reason"] for x in result["blockers"]])

    def test_evidence_requires_https_and_iso_date(self):
        with self.assertRaises(RightsError):
            self.r.add_evidence("code", "http://example.com", "Authority", "2026-10-31", "Excerpt")
        with self.assertRaises(RightsError):
            self.r.add_evidence("code", "https://example.com", "Authority", "not-a-date", "Excerpt")

    def test_dossier_keeps_evidence_and_assessments(self):
        self.r.assess("code", "preservation", "RIGHTS_UNCLEAR",
                      "Chain of title is missing", "game-rights-agent")
        dossier = self.r.dossier("retro-001")
        self.assertEqual(dossier["components"][0]["component_id"], "code")
        self.assertTrue(dossier["components"][0]["evidence"])


if __name__ == "__main__":
    unittest.main()
