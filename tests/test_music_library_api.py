"""End-to-end checks for the host's rights-gated local music API."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from host.server import Handler, StreamioVHTTPServer


COMPONENTS = ["composition", "sound_recording", "performance"]


def approved_rights(**overrides):
    grant = {
        "territory": "DE",
        "usage": "live_stream",
        "components": list(COMPONENTS),
        "state": "approved",
        "cost_eur": 0,
        "evidence": [{
            "url": "https://rights.example.test/permission",
            "accessed_at": "2026-11-25",
            "source_title": "Permission statement",
            "publisher": "Track rightsholder",
            "section": "Streaming permissions",
            "kind": "rightsholder_permission",
            "summary": "The rightsholder grants this use without a fee.",
        }],
        "rightsholder": "Track rightsholder",
        "grant_basis": "direct_permission",
        "attribution": "Credit the artist as listed.",
        "reviewed_by": "local-reviewer",
        "reviewed_at": "2026-11-25",
    }
    grant.update(overrides)
    return grant


class MusicLibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("StreamioV local host", encoding="utf-8")
        self.raw = self.root / "raw"
        (self.raw / "music").mkdir(parents=True)
        self.audio_root = self.root / "audio"
        self.audio_root.mkdir()
        (self.audio_root / "creator-track.wav").write_bytes(b"RIFF-approved-local-audio")
        self.track = {
            "id": "creator-track",
            "title": "Creator Track",
            "artist": "StreamioV Creator",
            "local_file": "creator-track.wav",
            "rights_components": list(COMPONENTS),
            "rights": [approved_rights()],
            "content_labels": [],
            "content_review": "approved",
        }
        self.write_catalog([self.track])
        self.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, self.site, self.root / "state",
            raw_data_root=self.raw, music_root=self.audio_root,
            trust_loopback_proxy=True,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def write_catalog(self, tracks):
        (self.raw / "music" / "rights_catalog.json").write_text(
            json.dumps({"schema_version": 2, "tracks": tracks}), encoding="utf-8"
        )

    def request(self, path, *, method="GET", headers=None):
        request = Request(self.base + path, method=method, headers=headers or {})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read(), dict(response.headers)
        except HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def get_json(self, path):
        status, body, _ = self.request(path)
        return status, json.loads(body)

    def test_gate_reports_only_exact_territory_and_usage(self):
        status, payload = self.get_json("/api/v1/music/gate?territory=DE&usage=live_stream")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        track = payload["tracks"][0]
        self.assertEqual(track["id"], "creator-track")
        self.assertTrue(track["allowed"])
        self.assertEqual(track["state"], "playable")
        status, other = self.get_json("/api/v1/music/gate?territory=DE&usage=saved_vod")
        self.assertEqual(status, 200)
        self.assertFalse(other["tracks"][0]["allowed"])
        self.assertEqual(other["tracks"][0]["state"], "rights_unknown")

    def test_approved_audio_is_served_without_exposing_paths(self):
        status, body, headers = self.request("/api/v1/music/audio/creator-track?territory=DE&usage=live_stream")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"RIFF-approved-local-audio")
        self.assertTrue(headers["Content-Type"].startswith("audio/"))
        self.assertEqual(headers["Access-Control-Allow-Origin"], "null")
        self.assertNotIn(str(self.audio_root), json.dumps(headers))

    def test_forwarded_external_peer_cannot_use_the_loopback_only_audio_route(self):
        status, body, _ = self.request(
            "/api/v1/music/audio/creator-track?territory=DE&usage=live_stream",
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "audio_loopback_only")

    def test_denied_track_audio_and_wrong_territory_are_blocked(self):
        status, payload, _ = self.request(
            "/api/v1/music/audio/creator-track?territory=AT&usage=live_stream"
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(payload)["error"], "rights_unknown")
        status, payload, _ = self.request("/api/v1/music/audio/unknown-track?territory=DE&usage=live_stream")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(payload)["error"], "unknown_track")

    def test_missing_audio_file_is_denied_even_with_approved_rights(self):
        (self.audio_root / "creator-track.wav").unlink()
        status, payload = self.get_json("/api/v1/music/gate?territory=DE&usage=live_stream")
        self.assertEqual(status, 200)
        self.assertEqual(payload["tracks"][0]["state"], "missing_local_audio")
        status, body, _ = self.request("/api/v1/music/audio/creator-track?territory=DE&usage=live_stream")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "missing_local_audio")

    def test_symlink_escape_is_never_playable(self):
        outside = self.root / "outside.wav"
        outside.write_bytes(b"outside")
        audio = self.audio_root / "creator-track.wav"
        audio.unlink()
        try:
            audio.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")
        status, body, _ = self.request("/api/v1/music/audio/creator-track?territory=DE&usage=live_stream")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "missing_local_audio")

    def test_dossier_separates_rights_evidence_from_content_review(self):
        status, payload = self.get_json("/api/v1/music/dossier?track=creator-track&territory=DE&usage=live_stream")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["requested_usage"], "live_stream")
        self.assertEqual(payload["content_review"]["state"], "approved")
        self.assertEqual(payload["rights_state"], "evidence_approved_by_local_reviewer")
        component = payload["components"][0]
        self.assertEqual(component["uses"][0]["grant_basis"], "direct_permission")
        self.assertTrue(component["uses"][0]["evidence"])
        self.assertNotIn(str(self.audio_root), json.dumps(payload))

    def test_invalid_requests_write_routes_and_status_are_honest(self):
        status, payload = self.get_json("/api/v1/music/gate?territory=de&usage=live_stream")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "territory_required")
        status, payload = self.get_json("/api/v1/music/gate?territory=DE&usage=stream")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "usage_not_supported")
        status, payload, _ = self.request("/api/v1/music/gate?territory=DE&usage=live_stream", method="POST")
        self.assertEqual(status, 405)
        status, payload = self.get_json("/api/v1/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["music_gate"]["catalog_available"])
        self.assertEqual(payload["music_gate"]["playable_catalog_tracks"], 1)

    def test_unreadable_catalog_fails_closed(self):
        (self.raw / "music" / "rights_catalog.json").write_text("{", encoding="utf-8")
        self.server.music_catalog.reload()
        status, payload = self.get_json("/api/v1/music/gate?territory=DE&usage=live_stream")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "music_catalog_unavailable")


if __name__ == "__main__":
    unittest.main()
