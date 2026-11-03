import json
import tempfile
import unittest
from pathlib import Path

from modules.music.library import MusicLibrary
from modules.music.research import render_markdown, rights_dossier


class MusicResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "track.wav").write_bytes(b"fixture")
        self.catalog = self.root / "catalog.json"

    def tearDown(self):
        self.temp.cleanup()

    def dossier(self, rights):
        track = {
            "id": "test-track", "title": "Test", "artist": "Creator",
            "local_file": "track.wav", "rights_components": ["composition", "lyrics"],
            "rights": rights, "content_labels": ["political"],
            "political_direction": "left", "content_review": "pending",
        }
        self.catalog.write_text(json.dumps({"schema_version": 2, "tracks": [track]}), encoding="utf-8")
        library = MusicLibrary.load(self.catalog, music_root=self.root)
        return rights_dossier(library, "test-track", territory="DE", usages=("live_stream",))

    def test_unrecorded_component_rights_stay_unknown(self):
        dossier = self.dossier([])
        self.assertEqual(dossier["rights_state"], "incomplete_or_unknown")
        self.assertEqual([item["uses"][0]["state"] for item in dossier["components"]], ["unknown", "unknown"])

    def test_dossier_keeps_component_evidence_and_content_review_separate(self):
        grant = {
            "territory": "DE", "usage": "live_stream", "components": ["composition"],
            "state": "approved", "cost_eur": 0,
            "evidence": [{
                "url": "https://rights.example.test/terms", "accessed_at": "2026-11-02",
                "source_title": "License", "publisher": "Creator", "section": "Streaming",
                "kind": "license_text", "summary": "Free streaming grant.",
            }],
            "grant_basis": "license", "license_id": "CC-BY-4.0", "rightsholder": "Creator",
            "attribution": "Credit Creator", "reviewed_by": "reviewer", "reviewed_at": "2026-11-02",
        }
        dossier = self.dossier([grant])
        composition = next(item for item in dossier["components"] if item["component"] == "composition")
        lyrics = next(item for item in dossier["components"] if item["component"] == "lyrics")
        self.assertEqual(composition["uses"][0]["state"], "approved")
        self.assertEqual(composition["uses"][0]["evidence"][0]["publisher"], "Creator")
        self.assertEqual(lyrics["uses"][0]["state"], "unknown")
        self.assertEqual(dossier["content_review"]["political_direction"], "left")
        self.assertEqual(dossier["content_review"]["state"], "pending")
        self.assertEqual(dossier["rights_state"], "incomplete_or_unknown")
        markdown = render_markdown(dossier)
        self.assertIn("[License](https://rights.example.test/terms)", markdown)
        self.assertIn("Political direction annotation", markdown)


if __name__ == "__main__":
    unittest.main()
