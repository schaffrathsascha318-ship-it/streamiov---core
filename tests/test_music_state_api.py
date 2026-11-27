"""HTTP checks for the owner-scoped persistent music state API."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from host.server import Handler, StreamioVHTTPServer


RIGHTS_COMPONENTS = ["composition", "sound_recording", "performance"]


def approved_rights():
    return {
        "territory": "DE",
        "usage": "live_stream",
        "components": RIGHTS_COMPONENTS,
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


class MusicStateApiTests(unittest.TestCase):
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
        (self.raw / "music" / "rights_catalog.json").write_text(json.dumps({
            "schema_version": 2,
            "tracks": [{
                "id": "creator-track",
                "title": "Creator Track",
                "artist": "StreamioV Creator",
                "local_file": "creator-track.wav",
                "rights_components": RIGHTS_COMPONENTS,
                "rights": [approved_rights()],
                "content_labels": [],
                "content_review": "approved",
            }],
        }), encoding="utf-8")
        self.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, self.site, self.root / "state",
            raw_data_root=self.raw, music_root=self.audio_root,
            trust_loopback_proxy=True, registration_open=True,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.origin = f"https://127.0.0.1:{self.server.server_port}"
        account = json.dumps({"username": "MusicOwner", "password": "a-long-local-password"}).encode()
        request = Request(self.base + "/api/v1/auth/register", data=account, method="POST", headers={
            "Content-Type": "application/json", "Origin": self.origin,
            "X-Forwarded-Proto": "https",
        })
        with urlopen(request, timeout=5) as response:
            self.cookie = response.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def catalog_track(self):
        return {
            "id": "creator-track",
            "title": "Creator Track",
            "artist": "StreamioV Creator",
            "source": "rights_catalog",
            "catalogId": "creator-track",
            "territory": "DE",
            "usage": "live_stream",
            "rightsState": "playable",
            "liveAllowed": True,
        }

    def local_track(self):
        return {
            "id": "local-" + uuid.uuid4().hex[:8],
            "title": "Local Demo",
            "artist": "Owner",
            "source": "local_import",
            "assetId": str(uuid.uuid4()),
            "liveAllowed": True,
        }

    def request(self, path, *, method="GET", payload=None, cookie=True, client=True, origin=None):
        headers = {}
        data = None
        if cookie:
            headers["Cookie"] = self.cookie
        if client:
            headers["X-Streamiov-Client"] = "studio"
        if origin is not None:
            headers["Origin"] = origin
            headers["X-Forwarded-Proto"] = "https"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def snapshot(self):
        status, payload = self.request("/api/v1/music/state")
        self.assertEqual(status, 200)
        return payload

    def post(self, path, action, payload=None, **kwargs):
        body = {"action": action}
        if payload is not None:
            body["payload"] = payload
        return self.request(path, method="POST", payload=body, **kwargs)

    def test_state_requires_session_studio_header_and_real_origin(self):
        status, payload = self.request("/api/v1/music/state", cookie=False)
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "authentication_required")
        status, payload = self.request("/api/v1/music/state", client=False)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "studio_client_header_required")
        status, payload = self.request("/api/v1/music/state", origin="https://attacker.example")
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "request_origin_not_allowed")
        status, payload = self.request("/api/v1/music/state", origin=self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload["schemaVersion"], 1)

    def test_queue_and_settings_are_persisted_and_local_imports_are_not_live_allowed(self):
        queue = [self.catalog_track(), self.local_track()]
        settings = {
            "currentIndex": 0, "shuffle": True, "repeat": False,
            "territory": "DE", "usage": "live_stream",
            "routes": ["stream", "monitor"], "volume": 0.65, "muted": False,
        }
        status, payload = self.post("/api/v1/music/state", "saveQueue", {"queue": queue, "settings": settings})
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in payload["queue"]], [item["id"] for item in queue])
        self.assertTrue(payload["settings"]["shuffle"])
        self.assertEqual(payload["settings"]["volume"], 0.65)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["queue"][0]["rightsState"], "playable")
        self.assertTrue(snapshot["queue"][0]["liveAllowed"])
        self.assertEqual(snapshot["queue"][1]["rightsState"], "local_unverified")
        self.assertFalse(snapshot["queue"][1]["liveAllowed"])
        self.assertEqual(set(snapshot["settings"]["routes"]), {"stream", "monitor"})

    def test_playlists_load_combine_and_delete(self):
        status, first = self.post("/api/v1/music/playlist", "save", {
            "name": "Approved", "origin": "creator", "tracks": [self.catalog_track()],
        })
        self.assertEqual(status, 200)
        status, second = self.post("/api/v1/music/playlist", "save", {
            "name": "Local", "origin": "creator", "tracks": [self.local_track()],
        })
        self.assertEqual(status, 200)
        ids = [entry["id"] for entry in second["playlists"]]
        status, combined = self.post("/api/v1/music/playlist", "combine", {
            "name": "Combined", "playlistIds": ids,
        })
        self.assertEqual(status, 200)
        combined_entry = next(entry for entry in combined["playlists"] if entry["name"] == "Combined")
        self.assertEqual(len(combined_entry["tracks"]), 2)
        status, loaded = self.post("/api/v1/music/playlist", "load", {"playlistId": combined_entry["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(len(loaded["queue"]), 2)
        self.assertEqual(loaded["settings"]["currentIndex"], 0)
        status, deleted = self.post("/api/v1/music/playlist", "delete", {"playlistId": combined_entry["id"]})
        self.assertEqual(status, 200)
        self.assertNotIn(combined_entry["id"], [entry["id"] for entry in deleted["playlists"]])

    def test_ai_uses_only_rights_approved_catalog_tracks(self):
        status, payload = self.post("/api/v1/music/ai-playlist", "create", {
            "prompt": "energetischer Stream-Intro", "territory": "DE", "limit": 8,
        })
        self.assertEqual(status, 200)
        created = next(entry for entry in payload["playlists"] if entry["name"] == "KI-Vorschlag")
        self.assertEqual(created["origin"], "ai_assistant")
        self.assertEqual(created["prompt"], "energetischer Stream-Intro")
        self.assertEqual(len(created["tracks"]), 1)
        self.assertEqual(created["tracks"][0]["source"], "rights_catalog")
        self.assertTrue(created["tracks"][0]["liveAllowed"])
        status, payload = self.post("/api/v1/music/ai-playlist", "improve", {
            "playlistId": created["id"], "prompt": "ruhiger Abend", "territory": "DE", "avoid": [],
        })
        self.assertEqual(status, 200, payload)
        improved = next(entry for entry in payload["playlists"] if entry["id"] == created["id"])
        self.assertEqual(improved["origin"], "ai_assistant")
        self.assertTrue(all(track["liveAllowed"] for track in improved["tracks"]))
        status, payload = self.post("/api/v1/music/ai-playlist", "create", {
            "prompt": "\x00", "territory": "DE",
        })
        self.assertEqual(status, 400)
        self.assertIn("prompt", payload["error"])

    def test_status_reports_persistent_state_store(self):
        status, payload = self.request("/api/v1/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["music_state_ready"])
        self.assertTrue(payload["music_state_requires_session"])


if __name__ == "__main__":
    unittest.main()
