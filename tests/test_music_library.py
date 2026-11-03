import json
import tempfile
import unittest
from pathlib import Path

from modules.music.library import ContentPolicy, MusicLibrary, MusicLibraryError


DEFAULT_COMPONENTS = ["composition", "sound_recording", "performance"]


def approved_rights(*, territory="DE", usage="live_stream", cost=0, components=None):
    return {
        "territory": territory,
        "usage": usage,
        "components": components or list(DEFAULT_COMPONENTS),
        "state": "approved",
        "cost_eur": cost,
        "evidence": [{
            "url": "https://rights.example.test/permission",
            "accessed_at": "2026-11-02",
            "source_title": "Permission statement",
            "publisher": "Track rightsholder",
            "section": "Streaming permissions",
            "kind": "rightsholder_permission",
            "summary": "Rightsholder grants the listed use for no fee.",
        }],
        "rightsholder": "Track rightsholder",
        "grant_basis": "direct_permission",
        "attribution": "Credit the artist as listed in the catalogue.",
        "reviewed_by": "local-reviewer",
        "reviewed_at": "2026-11-02",
    }


class MusicLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "creator-track.wav").write_bytes(b"local-audio-fixture")
        self.catalog = self.root / "catalog.json"

    def tearDown(self):
        self.temp.cleanup()

    def load_track(self, **overrides):
        track = {
            "id": "creator-track",
            "title": "Creator Track",
            "artist": "StreamioV Creator",
            "local_file": "creator-track.wav",
            "rights_components": list(DEFAULT_COMPONENTS),
            "rights": [approved_rights()],
            "content_labels": [],
            "content_review": "approved",
        }
        track.update(overrides)
        self.catalog.write_text(json.dumps({"schema_version": 2, "tracks": [track]}), encoding="utf-8")
        return MusicLibrary.load(self.catalog, music_root=self.root)

    def test_exact_free_human_reviewed_grant_allows_only_requested_usage(self):
        library = self.load_track()
        allowed = library.assess("creator-track", territory="DE", usage="live_stream")
        denied = library.assess("creator-track", territory="DE", usage="saved_vod")
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.local_path, self.root / "creator-track.wav")
        self.assertEqual(denied.state, "rights_unknown")

    def test_unknown_rights_and_paid_grants_fail_closed(self):
        unknown = self.load_track(rights=[])
        paid_grant = approved_rights(cost=1)
        paid_grant["state"] = "candidate"
        paid = self.load_track(rights=[paid_grant])
        self.assertEqual(unknown.assess("creator-track", territory="DE", usage="live_stream").state, "rights_unknown")
        self.assertEqual(paid.assess("creator-track", territory="DE", usage="live_stream").state, "rights_unverified")

    def test_every_required_track_component_needs_exact_use_and_territory_clearance(self):
        composition_only = approved_rights(components=["composition"])
        library = self.load_track(rights=[composition_only])
        result = library.assess("creator-track", territory="DE", usage="live_stream")
        self.assertEqual(result.state, "rights_unknown")

        with_lyrics = self.load_track(rights_components=[*DEFAULT_COMPONENTS, "lyrics"])
        result = with_lyrics.assess("creator-track", territory="DE", usage="live_stream")
        self.assertEqual(result.state, "rights_unknown")

    def test_hate_and_explicit_content_are_blocked_by_default_politics_requires_review(self):
        explicit = self.load_track(content_labels=["sexual_explicit"], content_review="pending")
        political = self.load_track(content_labels=["political"], political_direction="left", content_review="pending")
        hate = self.load_track(content_labels=["hate_or_threats"], content_review="approved")
        self.assertEqual(explicit.assess("creator-track", territory="DE", usage="live_stream").state, "content_blocked")
        self.assertEqual(political.assess("creator-track", territory="DE", usage="live_stream").state, "content_review_required")
        self.assertEqual(hate.assess("creator-track", territory="DE", usage="live_stream").state, "content_blocked")
        explicit_review_policy = ContentPolicy(
            blocked_labels=frozenset(), review_labels=frozenset({"sexual_explicit"})
        )
        self.assertEqual(
            explicit.assess("creator-track", territory="DE", usage="live_stream", policy=explicit_review_policy).state,
            "content_review_required",
        )
        reviewed = political.assess("creator-track", territory="DE", usage="live_stream", policy=ContentPolicy(review_labels=frozenset()))
        self.assertTrue(reviewed.allowed, "political direction alone must not block a track")

    def test_approved_grants_require_https_evidence_and_human_review(self):
        grant = approved_rights()
        grant["evidence"][0]["url"] = "http://rights.example.test/permission"
        with self.assertRaises(MusicLibraryError):
            self.load_track(rights=[grant])
        grant = approved_rights()
        grant["reviewed_by"] = None
        with self.assertRaises(MusicLibraryError):
            self.load_track(rights=[grant])
        grant = approved_rights()
        grant["attribution"] = None
        with self.assertRaises(MusicLibraryError):
            self.load_track(rights=[grant])

    def test_audio_must_exist_inside_the_local_music_root(self):
        missing = self.load_track(local_file="missing.wav")
        self.assertEqual(missing.assess("creator-track", territory="DE", usage="live_stream").state, "missing_local_audio")
        with self.assertRaises(MusicLibraryError):
            self.load_track(local_file="../outside.wav")

    def test_political_direction_requires_political_label_and_is_recorded_evenly(self):
        with self.assertRaises(MusicLibraryError):
            self.load_track(content_labels=[], political_direction="right")
        right = self.load_track(content_labels=["political"], political_direction="right", content_review="approved")
        left = self.load_track(content_labels=["political"], political_direction="left", content_review="approved")
        policy = ContentPolicy(review_labels=frozenset())
        self.assertTrue(right.assess("creator-track", territory="DE", usage="live_stream", policy=policy).allowed)
        self.assertTrue(left.assess("creator-track", territory="DE", usage="live_stream", policy=policy).allowed)


if __name__ == "__main__":
    unittest.main()
