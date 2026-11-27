"""Persistent owner-scoped queue, playlists and local AI suggestions for music."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

MUSIC_STATE_SCHEMA_VERSION = 1
MAX_PLAYLISTS = 100
MAX_TRACKS = 200
MAX_QUEUE = 100
MAX_NAME = 120
MAX_DESCRIPTION = 600
MAX_PROMPT = 500
MAX_ID = 80
TRACK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
CATALOG_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
UUID_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TERRITORY = re.compile(r"^[A-Z]{2}$")
USAGES = frozenset({"local_playback", "live_stream", "saved_vod", "download"})
SOURCES = frozenset({"local_import", "rights_catalog"})
ORIGINS = frozenset({"creator", "ai_assistant", "catalog"})
ROUTES = frozenset({"stream", "monitor", "headphones", "communications"})
KEYWORD_HINTS = (
    (("ruhig", "calm", "chill", "fokus", "focus", "leise"), "calm"),
    (("energie", "energetisch", "energetic", "party", "tanz", "dance", "upbeat"), "energetic"),
    (("stream", "intro", "start", "sendung"), "stream"),
    (("abend", "evening", "entspannung", "relax"), "evening"),
)


class MusicStateError(ValueError):
    """Safe-to-return validation error for music state requests."""


def _text(value: object, field: str, *, maximum: int = MAX_NAME, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise MusicStateError(f"{field} must be a string.")
    text = " ".join(value.split())
    if required and not text:
        raise MusicStateError(f"{field} must not be empty.")
    if len(text) > maximum:
        raise MusicStateError(f"{field} is too long.")
    if "\x00" in text:
        raise MusicStateError(f"{field} contains an invalid character.")
    return text


def _identifier(value: object, field: str, pattern: re.Pattern[str] = TRACK_ID) -> str:
    text = _text(value, field, maximum=MAX_ID)
    if not pattern.fullmatch(text):
        raise MusicStateError(f"{field} has an invalid format.")
    return text


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_track(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise MusicStateError("Every track must be an object.")
    source = raw.get("source")
    if source not in SOURCES:
        raise MusicStateError("track source is unsupported.")
    track_id = _identifier(raw.get("id"), "track id")
    title = _text(raw.get("title"), "track title", maximum=200)
    artist = _text(raw.get("artist"), "track artist", maximum=200, required=False)
    territory = raw.get("territory", "")
    usage = raw.get("usage", "")
    if source == "local_import":
        asset_id = _identifier(raw.get("assetId"), "asset id", UUID_ID)
        live_allowed = False
        rights_state = "local_unverified"
        catalog_id = ""
        territory = ""
        usage = ""
    else:
        catalog_id = _identifier(raw.get("catalogId"), "catalog id", CATALOG_ID)
        asset_id = ""
        territory = _text(territory, "territory", maximum=2).upper()
        if not TERRITORY.fullmatch(territory):
            raise MusicStateError("territory must be an ISO country code.")
        if usage not in USAGES:
            raise MusicStateError("usage is unsupported.")
        live_allowed = raw.get("liveAllowed") is True
        rights_state = _text(raw.get("rightsState", "rights_unknown"), "rights state", maximum=60)
        if not live_allowed or rights_state != "playable":
            live_allowed = False
            rights_state = "rights_unknown"
    return {
        "id": track_id,
        "title": title,
        "artist": artist,
        "source": source,
        "assetId": asset_id,
        "catalogId": catalog_id,
        "territory": territory,
        "usage": usage,
        "rightsState": rights_state,
        "liveAllowed": live_allowed,
    }


def clean_tracks(value: object, *, maximum: int = MAX_TRACKS) -> list[dict]:
    if not isinstance(value, list) or len(value) > maximum:
        raise MusicStateError(f"At most {maximum} tracks are allowed.")
    tracks = [clean_track(item) for item in value]
    seen: set[str] = set()
    for track in tracks:
        if track["id"] in seen:
            raise MusicStateError("Duplicate tracks are not allowed.")
        seen.add(track["id"])
    return tracks


def clean_settings(value: object, queue_length: int) -> dict:
    if not isinstance(value, dict):
        raise MusicStateError("Music settings must be an object.")
    index = value.get("currentIndex", -1)
    if not isinstance(index, int) or isinstance(index, bool) or index < -1 or index >= queue_length:
        raise MusicStateError("currentIndex is out of range.")
    territory = value.get("territory", "DE")
    if not isinstance(territory, str) or not TERRITORY.fullmatch(territory):
        raise MusicStateError("territory must be an ISO country code.")
    usage = value.get("usage", "live_stream")
    if usage not in USAGES:
        raise MusicStateError("usage is unsupported.")
    return {
        "currentIndex": -1 if queue_length == 0 else index,
        "shuffle": value.get("shuffle") is True,
        "repeat": value.get("repeat") is True,
        "territory": territory,
        "usage": usage,
        "routes": sorted(ROUTES.intersection(value.get("routes") or [])),
        "volume": _volume(value.get("volume", 0.5)),
        "muted": value.get("muted") is True,
    }


def _volume(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.5
    if not 0 <= float(value) <= 1:
        return 0.5
    return round(float(value), 4)


def suggest_tracks(prompt: object, available: object, *, limit: int = 16, avoid: object = None) -> list[dict]:
    text = _text(prompt, "prompt", maximum=MAX_PROMPT)
    tokens = [token for token in re.findall(r"[a-z0-9äöüß]+", text.lower()) if len(token) > 2]
    modes = {mode for words, mode in KEYWORD_HINTS if any(word in text.lower() for word in words)}
    if not isinstance(available, list):
        raise MusicStateError("available tracks must be an array.")
    avoided = set()
    if isinstance(avoid, list):
        avoided = {str(item) for item in avoid[:MAX_TRACKS]}
    candidates = []
    for item in available:
        if not isinstance(item, dict) or item.get("source") != "rights_catalog" or item.get("liveAllowed") is not True:
            continue
        if item.get("id") in avoided or item.get("catalogId") in avoided:
            continue
        try:
            track = clean_track(item)
        except MusicStateError:
            continue
        title = track["title"].lower()
        artist = track["artist"].lower()
        score = sum(3 for token in tokens if token in title) + sum(2 for token in tokens if token in artist)
        if "calm" in modes and any(word in title for word in ("ruhig", "calm", "slow", "ballad")):
            score += 4
        if "energetic" in modes and any(word in title for word in ("dance", "party", "beat", "mix")):
            score += 4
        if "evening" in modes and any(word in title for word in ("abend", "night", "lounge")):
            score += 4
        if "stream" in modes and any(word in title for word in ("intro", "theme", "start")):
            score += 4
        score += 1 if track["rightsState"] == "playable" else 0
        candidates.append((score, track))
    if not candidates:
        raise MusicStateError("no rights-approved tracks are available for a suggestion.")
    selected: list[dict] = []
    artist_counts: dict[str, int] = {}
    for _score, track in sorted(candidates, key=lambda item: (-item[0], item[1]["id"])):
        if len(selected) >= max(1, min(limit, MAX_TRACKS)):
            break
        key = track["artist"].lower()
        if key and artist_counts.get(key, 0) >= 2:
            continue
        selected.append(track)
        artist_counts[key] = artist_counts.get(key, 0) + 1
    return selected


class MusicStateStore:
    """SQLite-backed local queue and playlists, scoped to one host account."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.database = self.data_dir / "music.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _transaction(self):
        with closing(self._connect()) as db:
            with db:
                yield db

    def _initialize(self) -> None:
        with self._transaction() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS playlists (
                    playlist_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS playlists_owner_updated ON playlists(owner_id, updated_at);
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    track_json TEXT NOT NULL,
                    PRIMARY KEY(playlist_id, position),
                    FOREIGN KEY(playlist_id) REFERENCES playlists(playlist_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS queue_items (
                    owner_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    track_json TEXT NOT NULL,
                    PRIMARY KEY(owner_id, position)
                );
                CREATE TABLE IF NOT EXISTS music_settings (
                    owner_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @staticmethod
    def _tracks(db: sqlite3.Connection, sql: str, parameters: tuple) -> list[dict]:
        result = []
        for row in db.execute(sql, parameters):
            try:
                parsed = json.loads(row["track_json"])
            except (TypeError, ValueError):
                continue
            try:
                result.append(clean_track(parsed))
            except MusicStateError:
                continue
        return result

    def _playlist_rows(self, db: sqlite3.Connection, owner_id: str, playlist_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM playlists WHERE owner_id = ?"
        parameters: tuple = (owner_id,)
        if playlist_id:
            sql += " AND playlist_id = ?"
            parameters = (owner_id, playlist_id)
        sql += " ORDER BY updated_at DESC, playlist_id"
        result = []
        for row in db.execute(sql, parameters):
            result.append({
                "id": row["playlist_id"],
                "name": row["name"],
                "description": row["description"],
                "origin": row["origin"],
                "prompt": row["prompt"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "tracks": self._tracks(
                    db,
                    "SELECT track_json FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
                    (row["playlist_id"],),
                ),
            })
        return result

    def snapshot(self, owner_id: object) -> dict:
        if not isinstance(owner_id, str) or not owner_id:
            raise MusicStateError("owner is required.")
        with closing(self._connect()) as db:
            queue = self._tracks(db, "SELECT track_json FROM queue_items WHERE owner_id = ? ORDER BY position", (owner_id,))
            row = db.execute("SELECT settings_json FROM music_settings WHERE owner_id = ?", (owner_id,)).fetchone()
            settings = clean_settings(json.loads(row["settings_json"]) if row else {}, len(queue))
            playlists = self._playlist_rows(db, owner_id)
        return {
            "ok": True,
            "schemaVersion": MUSIC_STATE_SCHEMA_VERSION,
            "queue": queue,
            "playlists": playlists,
            "settings": settings,
        }

    def save_queue(self, owner_id: object, payload: object) -> dict:
        if not isinstance(owner_id, str) or not owner_id:
            raise MusicStateError("owner is required.")
        if not isinstance(payload, dict):
            raise MusicStateError("payload must be an object.")
        queue = clean_tracks(payload.get("queue") or [], maximum=MAX_QUEUE)
        settings = clean_settings(payload.get("settings") or {}, len(queue))
        now = _timestamp()
        with self._transaction() as db:
            db.execute("DELETE FROM queue_items WHERE owner_id = ?", (owner_id,))
            db.executemany(
                "INSERT INTO queue_items(owner_id, position, track_json) VALUES(?,?,?)",
                [(owner_id, index, json.dumps(track, ensure_ascii=False)) for index, track in enumerate(queue)],
            )
            db.execute(
                "INSERT INTO music_settings(owner_id, settings_json, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(owner_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at",
                (owner_id, json.dumps(settings, ensure_ascii=False), now),
            )
        return self.snapshot(owner_id)

    def save_playlist(self, owner_id: object, payload: object) -> dict:
        if not isinstance(owner_id, str) or not owner_id:
            raise MusicStateError("owner is required.")
        if not isinstance(payload, dict):
            raise MusicStateError("payload must be an object.")
        name = _text(payload.get("name"), "playlist name")
        description = _text(payload.get("description", ""), "description", maximum=MAX_DESCRIPTION, required=False)
        origin = payload.get("origin", "creator")
        if origin not in ORIGINS:
            raise MusicStateError("playlist origin is unsupported.")
        prompt = _text(payload.get("prompt", ""), "prompt", maximum=MAX_PROMPT, required=False)
        tracks = clean_tracks(payload.get("tracks") or [])
        playlist_id = payload.get("id") or str(uuid.uuid4())
        playlist_id = _identifier(playlist_id, "playlist id", UUID_ID)
        now = _timestamp()
        with self._transaction() as db:
            existing = db.execute(
                "SELECT 1 FROM playlists WHERE playlist_id = ? AND owner_id = ?", (playlist_id, owner_id)
            ).fetchone()
            if existing is None:
                count = db.execute("SELECT COUNT(*) FROM playlists WHERE owner_id = ?", (owner_id,)).fetchone()[0]
                if count >= MAX_PLAYLISTS:
                    raise MusicStateError("playlist limit reached.")
                db.execute(
                    "INSERT INTO playlists(playlist_id, owner_id, name, description, origin, prompt, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (playlist_id, owner_id, name, description, origin, prompt, now, now),
                )
            else:
                db.execute(
                    "UPDATE playlists SET name=?, description=?, origin=?, prompt=?, updated_at=? "
                    "WHERE playlist_id=? AND owner_id=?",
                    (name, description, origin, prompt, now, playlist_id, owner_id),
                )
            db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
            db.executemany(
                "INSERT INTO playlist_tracks(playlist_id, position, track_json) VALUES(?,?,?)",
                [(playlist_id, index, json.dumps(track, ensure_ascii=False)) for index, track in enumerate(tracks)],
            )
        return self.snapshot(owner_id)

    def delete_playlist(self, owner_id: object, playlist_id: object) -> dict:
        if not isinstance(owner_id, str) or not owner_id:
            raise MusicStateError("owner is required.")
        playlist_id = _identifier(playlist_id, "playlist id", UUID_ID)
        with self._transaction() as db:
            db.execute("DELETE FROM playlists WHERE playlist_id = ? AND owner_id = ?", (playlist_id, owner_id))
        return self.snapshot(owner_id)

    def load_playlist(self, owner_id: object, playlist_id: object) -> dict:
        if not isinstance(owner_id, str) or not owner_id:
            raise MusicStateError("owner is required.")
        playlist_id = _identifier(playlist_id, "playlist id", UUID_ID)
        with closing(self._connect()) as db:
            playlists = self._playlist_rows(db, owner_id, playlist_id)
        if not playlists:
            raise MusicStateError("playlist_not_found")
        return self.save_queue(owner_id, {
            "queue": playlists[0]["tracks"],
            "settings": {"currentIndex": 0 if playlists[0]["tracks"] else -1},
        })

    def combine_playlists(self, owner_id: object, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise MusicStateError("payload must be an object.")
        name = _text(payload.get("name"), "playlist name")
        ids = payload.get("playlistIds")
        if not isinstance(ids, list) or not ids or len(ids) > MAX_PLAYLISTS:
            raise MusicStateError("playlistIds must be a non-empty array.")
        clean_ids = [_identifier(item, "playlist id", UUID_ID) for item in ids]
        with closing(self._connect()) as db:
            chosen = [entry for item in clean_ids for entry in self._playlist_rows(db, owner_id, item)]
        tracks: list[dict] = []
        seen: set[str] = set()
        for playlist in chosen:
            for track in playlist["tracks"]:
                if track["id"] not in seen:
                    seen.add(track["id"])
                    tracks.append(track)
        if len(tracks) > MAX_TRACKS:
            raise MusicStateError("combination exceeds the track limit.")
        return self.save_playlist(owner_id, {
            "name": name,
            "description": "Kombination aus " + str(len(chosen)) + " Playlist(s).",
            "origin": "creator",
            "tracks": tracks,
        })

    def ai_playlist(self, owner_id: object, payload: object, available: object) -> dict:
        if not isinstance(payload, dict):
            raise MusicStateError("payload must be an object.")
        prompt = _text(payload.get("prompt"), "prompt", maximum=MAX_PROMPT)
        requested = payload.get("limit", 16)
        if not isinstance(requested, int) or isinstance(requested, bool) or not 1 <= requested <= MAX_TRACKS:
            raise MusicStateError("limit is out of range.")
        tracks = suggest_tracks(prompt, available, limit=requested, avoid=payload.get("avoid"))
        name = _text(payload.get("name", "KI-Vorschlag"), "playlist name")
        return self.save_playlist(owner_id, {
            "name": name,
            "description": "Lokaler KI-Vorschlag aus rechtlich geprüften Titeln: " + prompt,
            "origin": "ai_assistant",
            "prompt": prompt,
            "tracks": tracks,
        })

    def improve_playlist(self, owner_id: object, payload: object, available: object) -> dict:
        if not isinstance(payload, dict):
            raise MusicStateError("payload must be an object.")
        playlist_id = _identifier(payload.get("playlistId"), "playlist id", UUID_ID)
        prompt = _text(payload.get("prompt"), "prompt", maximum=MAX_PROMPT)
        with closing(self._connect()) as db:
            playlists = self._playlist_rows(db, owner_id, playlist_id)
        if not playlists:
            raise MusicStateError("playlist_not_found")
        original = playlists[0]
        avoid = payload.get("avoid")
        if not isinstance(avoid, list):
            avoid = [track["id"] for track in original["tracks"]]
        tracks = suggest_tracks(prompt, available, limit=min(MAX_TRACKS, max(len(original["tracks"]), 8)), avoid=avoid)
        keep = [track for track in original["tracks"] if track["liveAllowed"] and track["id"] not in {item["id"] for item in tracks}]
        combined = (tracks + keep)[:MAX_TRACKS]
        return self.save_playlist(owner_id, {
            "id": playlist_id,
            "name": original["name"],
            "description": "KI-gepflegter Vorschlag: " + prompt,
            "origin": "ai_assistant",
            "prompt": prompt,
            "tracks": combined,
        })
