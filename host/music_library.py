"""Read-only host service for the fail-closed local music rights gate.

No audio is downloaded, uploaded, or purchased here. A track is playable only
when modules.music.library approves the exact territory and use for every
required component and the audio file stays inside the configured local root.
"""
from __future__ import annotations

from pathlib import Path

from modules.music.library import (
    TRACK_ID,
    USES,
    MusicLibrary,
    MusicLibraryError,
)
from modules.music.research import rights_dossier


MAX_AUDIO_BYTES = 32 * 1024 * 1024


class HostMusicLibraryError(ValueError):
    """Raised for invalid host-level music requests or an unusable catalogue."""


class HostMusicLibrary:
    def __init__(self, catalog_path: str | Path, music_root: str | Path) -> None:
        self.catalog_path = Path(catalog_path).resolve()
        self.music_root = Path(music_root).resolve()
        self.library: MusicLibrary | None = None
        self.error: str | None = None
        self.reload()

    def reload(self) -> None:
        try:
            self.library = MusicLibrary.load(self.catalog_path, music_root=self.music_root)
            self.error = None
        except (MusicLibraryError, OSError, ValueError) as exc:
            self.library = None
            self.error = type(exc).__name__

    def status(self) -> dict:
        return {
            "catalog_available": self.library is not None,
            "catalog_error": self.error,
            "playable_catalog_tracks": len(self.library.tracks) if self.library else 0,
            "audio_root_configured": self.music_root.is_dir(),
            "max_audio_bytes": MAX_AUDIO_BYTES,
        }

    def _library(self) -> MusicLibrary:
        if self.library is None:
            raise HostMusicLibraryError("music_catalog_unavailable")
        return self.library

    @staticmethod
    def _validate_request(territory: str, usage: str) -> None:
        if not isinstance(territory, str) or len(territory) != 2 or not territory.isupper() or not territory.isalpha():
            raise HostMusicLibraryError("territory_required")
        if usage not in USES:
            raise HostMusicLibraryError("usage_not_supported")

    def gate(self, territory: str, usage: str) -> dict:
        self._validate_request(territory, usage)
        library = self._library()
        results = library.list_playable(territory=territory, usage=usage)
        tracks = []
        for item in results:
            track = library.tracks[item.track_id]
            tracks.append({
                "id": item.track_id,
                "title": track.title,
                "artist": track.artist,
                "allowed": item.allowed,
                "state": item.state,
                "reasons": list(item.reasons),
            })
        return {
            "ok": True,
            "territory": territory,
            "usage": usage,
            "count": len(tracks),
            "tracks": tracks,
            "notice": "Only zero-cost, locally reviewed rights for the exact territory and use are playable. No external licence is purchased or checked at playback time.",
        }

    def dossier(self, track_id: str, territory: str, usage: str) -> dict:
        self._validate_request(territory, usage)
        if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
            raise HostMusicLibraryError("invalid_track_id")
        library = self._library()
        if track_id not in library.tracks:
            raise HostMusicLibraryError("track_not_in_local_catalogue")
        payload = rights_dossier(library, track_id, territory=territory, usages=(usage,))
        payload["ok"] = True
        payload["requested_usage"] = usage
        return payload

    def playable_audio(self, track_id: str, territory: str, usage: str) -> tuple[Path, dict]:
        self._validate_request(territory, usage)
        if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
            raise HostMusicLibraryError("invalid_track_id")
        library = self._library()
        result = library.assess(track_id, territory=territory, usage=usage)
        if not result.allowed or result.local_path is None:
            raise HostMusicLibraryError(result.state)
        if result.local_path.stat().st_size > MAX_AUDIO_BYTES:
            raise HostMusicLibraryError("audio_file_too_large")
        track = library.tracks[track_id]
        metadata = {
            "id": track_id,
            "title": track.title,
            "artist": track.artist,
            "territory": territory,
            "usage": usage,
            "rights_state": result.state,
        }
        return result.local_path, metadata
