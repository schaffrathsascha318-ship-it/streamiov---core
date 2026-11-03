"""Read-only catalog store seeded from the repository's raw-data JSON.

The store deliberately lives in its own SQLite database inside the host data
directory. It never opens ``data/db/*.sqlite3`` (the legacy account database)
and never imports credentials, sessions, devices, or platform connections.

Seeding is idempotent: rows written from JSON use ``source = 'seed'`` and are
replaced on every successful import, while rows with another source are kept.
A missing or invalid JSON file leaves the previous catalog rows in place and is
reported through :meth:`DataStore.summary` instead of crashing the host.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any


SCHEMA_VERSION = 1
MAX_SOURCE_BYTES = 2 * 1024 * 1024
DEFAULT_RAW_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"

GIFT_SOURCE = "game_actions/gift_catalog.json"
GAME_SOURCE = "game_actions/games.json"
ACTION_SOURCE = "game_actions/actions.json"
PLAYLIST_SOURCE = "music/playlists.json"
RIGHTS_SOURCE = "music/rights_catalog.json"
TEMPLATE_SOURCES = (
    ("overlays/pro_builder.json", "overlay", "pro_builder", "Professional Overlay Builder"),
    ("stickers/builder.json", "sticker", "sticker_builder", "Sticker Builder"),
    ("stickers/ai_action_templates.json", "action", "ai_action_templates", "KI-Aktionsvorlagen"),
    ("games/new_game_preparation.json", "game", "new_game_preparation", "Neue-Spiel-Vorbereitung"),
    ("games/own_game_action_preparation.json", "game", "own_game_action_preparation", "Eigene-Spiel-Aktionen"),
)

CATALOG_KINDS = ("summary", "gifts", "games", "music", "templates")


class DataSeedError(ValueError):
    """Safe-to-report raw-data import problem."""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: Any, *, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _identifier(value: Any, *, field: str) -> str:
    text = _text(value)
    if not text or len(text) > 200:
        raise DataSeedError(f"Invalid {field}.")
    return text


def _integer(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _boolean(value: Any, *, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


class DataStore:
    """SQLite catalog seeded from repository JSON; exposed as read-only data."""

    def __init__(self, data_dir: str | Path, raw_data_root: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.raw_data_root = Path(raw_data_root or DEFAULT_RAW_DATA_ROOT).expanduser().resolve()
        self.database = self.data_dir / "streamiov-data.sqlite3"
        self._lock = threading.Lock()
        self._seed_report: dict[str, Any] = {
            "ok": False,
            "seeded_at": None,
            "errors": ["Noch nicht aus Rohdaten befüllt."],
            "sources": [],
        }
        self._initialize()
        self.seed()

    # ------------------------------------------------------------------ setup
    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if read_only:
            connection.execute("PRAGMA query_only = ON")
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
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS catalog_sources (
                    path TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    imported_at INTEGER NOT NULL,
                    item_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gifts (
                    gift_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    streamiov_points INTEGER NOT NULL DEFAULT 0,
                    tiktok_gift_id TEXT,
                    svg TEXT,
                    custom INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'unknown',
                    animation TEXT,
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gift_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    trigger_json TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'unknown',
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS like_milestones (
                    count INTEGER PRIMARY KEY,
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS music_playlists (
                    playlist_id TEXT PRIMARY KEY,
                    streamer_id TEXT,
                    name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    volume REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT,
                    updated_at TEXT,
                    source TEXT NOT NULL DEFAULT 'seed'
                );
                CREATE TABLE IF NOT EXISTS music_tracks (
                    track_id TEXT PRIMARY KEY,
                    playlist_id TEXT NOT NULL REFERENCES music_playlists(playlist_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    source TEXT,
                    rights_status TEXT NOT NULL DEFAULT 'unknown',
                    position INTEGER NOT NULL DEFAULT 0,
                    rights_json TEXT NOT NULL DEFAULT '{}',
                    source_kind TEXT NOT NULL DEFAULT 'seed'
                );
                CREATE TABLE IF NOT EXISTS music_rights (
                    track_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    rights_source TEXT,
                    license TEXT,
                    status TEXT NOT NULL DEFAULT 'unknown',
                    rights_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS games (
                    game_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT,
                    interface_status TEXT NOT NULL DEFAULT 'unknown',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS game_actions (
                    action_id TEXT PRIMARY KEY,
                    game_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    trigger_type TEXT,
                    trigger_json TEXT NOT NULL DEFAULT '{}',
                    execution_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_templates (
                    template_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'spec_only',
                    local_only INTEGER NOT NULL DEFAULT 1,
                    spec_json TEXT NOT NULL,
                    origin TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at INTEGER NOT NULL
                );
            """)
            template_columns = {
                row[1] for row in db.execute("PRAGMA table_info(studio_templates)")
            }
            if "origin" not in template_columns:
                db.execute(
                    "ALTER TABLE studio_templates ADD COLUMN origin TEXT NOT NULL DEFAULT ''"
                )
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ import
    def _read_source(self, relative_path: str) -> tuple[Any, bytes]:
        candidate = (self.raw_data_root / relative_path).resolve()
        try:
            candidate.relative_to(self.raw_data_root)
        except ValueError as exc:
            raise DataSeedError(f"Raw-data path escapes the configured root: {relative_path}") from exc
        try:
            if not candidate.is_file():
                raise DataSeedError(f"Raw-data file is missing: {relative_path}")
            if candidate.stat().st_size > MAX_SOURCE_BYTES:
                raise DataSeedError(f"Raw-data file is too large: {relative_path}")
            payload = candidate.read_bytes()
        except OSError as exc:
            raise DataSeedError(f"Raw-data file is unreadable: {relative_path}") from exc
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise DataSeedError(f"Raw-data file is not valid JSON: {relative_path}") from exc
        return parsed, payload

    def _record_source(self, db: sqlite3.Connection, relative_path: str, payload: bytes,
                       item_count: int, now: int) -> None:
        db.execute(
            """INSERT INTO catalog_sources(path,sha256,bytes,imported_at,item_count)
               VALUES(?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                   sha256=excluded.sha256, bytes=excluded.bytes,
                   imported_at=excluded.imported_at, item_count=excluded.item_count""",
            (relative_path, hashlib.sha256(payload).hexdigest(), len(payload), now, item_count),
        )

    def seed(self) -> dict[str, Any]:
        """Import every known JSON source. Safe to run repeatedly."""
        with self._lock:
            errors: list[str] = []
            sources: list[dict[str, Any]] = []
            now = int(time.time())

            loaded: dict[str, tuple[Any, bytes] | None] = {}
            for relative_path in (
                GIFT_SOURCE, GAME_SOURCE, ACTION_SOURCE, PLAYLIST_SOURCE, RIGHTS_SOURCE,
                *(source[0] for source in TEMPLATE_SOURCES),
            ):
                try:
                    loaded[relative_path] = self._read_source(relative_path)
                except DataSeedError as exc:
                    loaded[relative_path] = None
                    errors.append(str(exc))

            with self._transaction() as db:
                self._seed_gifts(db, loaded, sources, errors, now)
                self._seed_games(db, loaded, sources, errors, now)
                self._seed_music(db, loaded, sources, errors, now)
                self._seed_templates(db, loaded, sources, errors, now)
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('schema_version',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('seeded_at',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(now),),
                )
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('import_policy',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("repository JSON only; legacy data/db databases are never read",),
                )

            self._seed_report = {
                "ok": not errors,
                "seeded_at": now,
                "errors": errors,
                "sources": sources,
            }
            return self.summary()

    def _seed_gifts(self, db: sqlite3.Connection, loaded: dict[str, tuple[Any, bytes] | None],
                    sources: list[dict[str, Any]], errors: list[str], now: int) -> None:
        entry = loaded.get(GIFT_SOURCE)
        if entry is None:
            return
        document, payload = entry
        if not isinstance(document, dict) or not isinstance(document.get("gifts"), list):
            errors.append(f"Unexpected gift catalog shape: {GIFT_SOURCE}")
            return
        gifts: list[dict[str, Any]] = []
        try:
            for raw in document["gifts"]:
                if not isinstance(raw, dict):
                    raise DataSeedError("Gift entries must be objects.")
                gifts.append({
                    "gift_id": _identifier(raw.get("id"), field="gift id"),
                    "name": _text(raw.get("name")) or _identifier(raw.get("id"), field="gift id"),
                    "points": max(0, _integer(raw.get("streamiov_points"))),
                    "tiktok_gift_id": _text(raw.get("tiktok_gift_id")) or None,
                    "svg": _text(raw.get("svg")) or None,
                    "custom": 1 if _boolean(raw.get("streamiov_custom")) else 0,
                    "status": _text(raw.get("status")) or "catalog_only",
                    "animation": _text(raw.get("animation")) or None,
                })
            milestones = sorted({
                _integer(value) for value in document.get("like_milestones", [])
                if _integer(value) > 0
            })
            rules: list[dict[str, Any]] = []
            for raw in document.get("rules", []) or []:
                if not isinstance(raw, dict):
                    continue
                trigger = raw.get("trigger") if isinstance(raw.get("trigger"), dict) else {}
                action = raw.get("action") if isinstance(raw.get("action"), dict) else {}
                rules.append({
                    "rule_id": _identifier(raw.get("id"), field="rule id"),
                    "name": _text(raw.get("name")) or "Unbenannte Regel",
                    "trigger_type": _text(trigger.get("type")) or "unknown",
                    "trigger_json": _json_text(trigger),
                    "action_type": _text(action.get("type")) or "unknown",
                    "action_json": _json_text(action),
                    "status": _text(raw.get("status")) or "planned",
                })
        except DataSeedError as exc:
            errors.append(f"{GIFT_SOURCE}: {exc}")
            return

        db.execute("DELETE FROM gifts WHERE source='seed'")
        db.execute("DELETE FROM gift_rules WHERE source='seed'")
        db.execute("DELETE FROM like_milestones WHERE source='seed'")
        db.executemany(
            """INSERT INTO gifts(gift_id,name,streamiov_points,tiktok_gift_id,svg,custom,
                                 status,animation,source,updated_at)
               VALUES(?,?,?,?,?,?,?,?,'seed',?)""",
            [(g["gift_id"], g["name"], g["points"], g["tiktok_gift_id"], g["svg"],
              g["custom"], g["status"], g["animation"], now) for g in gifts],
        )
        db.executemany(
            """INSERT INTO like_milestones(count,source,updated_at) VALUES(?,'seed',?)""",
            [(count, now) for count in milestones],
        )
        db.executemany(
            """INSERT INTO gift_rules(rule_id,name,trigger_type,trigger_json,action_type,
                                      action_json,status,source,updated_at)
               VALUES(?,?,?,?,?,?,?,'seed',?)""",
            [(r["rule_id"], r["name"], r["trigger_type"], r["trigger_json"],
              r["action_type"], r["action_json"], r["status"], now) for r in rules],
        )
        db.execute(
            "INSERT INTO meta(key,value) VALUES('points_note',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_text(document.get("points_note")),),
        )
        item_count = len(gifts) + len(milestones) + len(rules)
        self._record_source(db, GIFT_SOURCE, payload, item_count, now)
        sources.append({"path": GIFT_SOURCE, "items": item_count})

    def _seed_games(self, db: sqlite3.Connection, loaded: dict[str, tuple[Any, bytes] | None],
                    sources: list[dict[str, Any]], errors: list[str], now: int) -> None:
        game_entry = loaded.get(GAME_SOURCE)
        action_entry = loaded.get(ACTION_SOURCE)
        games: list[dict[str, Any]] | None = None
        actions: list[dict[str, Any]] | None = None
        if game_entry is not None:
            document, payload = game_entry
            if not isinstance(document, list):
                errors.append(f"Unexpected game catalog shape: {GAME_SOURCE}")
            else:
                try:
                    games = [{
                        "game_id": _identifier(raw.get("game_id"), field="game id"),
                        "name": _text(raw.get("name")) or _identifier(raw.get("game_id"), field="game id"),
                        "version": _text(raw.get("version")) or None,
                        "interface_status": _text(raw.get("interface_status")) or "unknown",
                        "capabilities": raw.get("capabilities") if isinstance(raw.get("capabilities"), list) else [],
                    } for raw in document if isinstance(raw, dict)]
                except DataSeedError as exc:
                    errors.append(f"{GAME_SOURCE}: {exc}")
                    games = None
        if action_entry is not None:
            document, payload = action_entry
            if not isinstance(document, list):
                errors.append(f"Unexpected game action shape: {ACTION_SOURCE}")
            else:
                try:
                    actions = [{
                        "action_id": _identifier(raw.get("id"), field="action id"),
                        "game_id": _identifier(raw.get("game_id"), field="game id"),
                        "name": _text(raw.get("name")) or "Unbenannte Aktion",
                        "description": _text(raw.get("description")),
                        "trigger_type": _text(raw.get("trigger_type")) or "unknown",
                        "trigger_json": _json_text(raw.get("trigger_config") or {}),
                        "execution_json": _json_text(raw.get("execution_config") or {}),
                        "status": _text(raw.get("status")) or "planned",
                    } for raw in document if isinstance(raw, dict)]
                except DataSeedError as exc:
                    errors.append(f"{ACTION_SOURCE}: {exc}")
                    actions = None

        if games is not None:
            db.execute("DELETE FROM games WHERE source='seed'")
            db.executemany(
                """INSERT INTO games(game_id,name,version,interface_status,capabilities_json,
                                     source,updated_at)
                   VALUES(?,?,?,?,?,'seed',?)""",
                [(g["game_id"], g["name"], g["version"], g["interface_status"],
                  _json_text(g["capabilities"]), now) for g in games],
            )
            self._record_source(db, GAME_SOURCE, game_entry[1], len(games), now)
            sources.append({"path": GAME_SOURCE, "items": len(games)})
        if actions is not None:
            db.execute("DELETE FROM game_actions WHERE source='seed'")
            db.executemany(
                """INSERT INTO game_actions(action_id,game_id,name,description,trigger_type,
                                            trigger_json,execution_json,status,source,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,'seed',?)""",
                [(a["action_id"], a["game_id"], a["name"], a["description"], a["trigger_type"],
                  a["trigger_json"], a["execution_json"], a["status"], now) for a in actions],
            )
            self._record_source(db, ACTION_SOURCE, action_entry[1], len(actions), now)
            sources.append({"path": ACTION_SOURCE, "items": len(actions)})

    def _seed_music(self, db: sqlite3.Connection, loaded: dict[str, tuple[Any, bytes] | None],
                    sources: list[dict[str, Any]], errors: list[str], now: int) -> None:
        playlist_entry = loaded.get(PLAYLIST_SOURCE)
        if playlist_entry is not None:
            document, payload = playlist_entry
            if not isinstance(document, list):
                errors.append(f"Unexpected playlist shape: {PLAYLIST_SOURCE}")
            else:
                try:
                    playlists: list[dict[str, Any]] = []
                    tracks: list[dict[str, Any]] = []
                    for raw in document:
                        if not isinstance(raw, dict):
                            continue
                        playlist_id = _identifier(raw.get("id"), field="playlist id")
                        playlists.append({
                            "playlist_id": playlist_id,
                            "streamer_id": _text(raw.get("streamer_id")) or None,
                            "name": _text(raw.get("name")) or "Unbenannte Playlist",
                            "active": 1 if _boolean(raw.get("active")) else 0,
                            "volume": float(raw.get("volume")) if isinstance(raw.get("volume"), (int, float))
                            and not isinstance(raw.get("volume"), bool) else 1.0,
                            "created_at": _text(raw.get("created_at")) or None,
                            "updated_at": _text(raw.get("updated_at")) or None,
                        })
                        for position, track in enumerate(raw.get("tracks") or []):
                            if not isinstance(track, dict):
                                continue
                            tracks.append({
                                "track_id": _identifier(track.get("id"), field="track id"),
                                "playlist_id": playlist_id,
                                "title": _text(track.get("title")) or "Unbenannter Titel",
                                "source": _text(track.get("source")) or None,
                                "rights_status": _text(track.get("rights_status")) or "unknown",
                                "position": position,
                                "rights_json": _json_text(track),
                            })
                except (DataSeedError, TypeError, ValueError) as exc:
                    errors.append(f"{PLAYLIST_SOURCE}: {exc}")
                else:
                    db.execute("DELETE FROM music_tracks WHERE source_kind='seed'")
                    db.execute("DELETE FROM music_playlists WHERE source='seed'")
                    db.executemany(
                        """INSERT INTO music_playlists(playlist_id,streamer_id,name,active,volume,
                                                       created_at,updated_at,source)
                           VALUES(?,?,?,?,?,?,?,'seed')""",
                        [(p["playlist_id"], p["streamer_id"], p["name"], p["active"],
                          p["volume"], p["created_at"], p["updated_at"]) for p in playlists],
                    )
                    db.executemany(
                        """INSERT INTO music_tracks(track_id,playlist_id,title,source,rights_status,
                                                    position,rights_json,source_kind)
                           VALUES(?,?,?,?,?,?,?,'seed')""",
                        [(t["track_id"], t["playlist_id"], t["title"], t["source"],
                          t["rights_status"], t["position"], t["rights_json"]) for t in tracks],
                    )
                    self._record_source(db, PLAYLIST_SOURCE, payload, len(playlists) + len(tracks), now)
                    sources.append({"path": PLAYLIST_SOURCE, "items": len(playlists) + len(tracks)})

        rights_entry = loaded.get(RIGHTS_SOURCE)
        if rights_entry is not None:
            document, payload = rights_entry
            raw_tracks = document.get("tracks") if isinstance(document, dict) else None
            if not isinstance(raw_tracks, list):
                errors.append(f"Unexpected rights catalog shape: {RIGHTS_SOURCE}")
            else:
                try:
                    rights = [{
                        "track_id": _identifier(raw.get("id") or raw.get("track_id"), field="rights track id"),
                        "title": _text(raw.get("title")) or "Unbenannter Titel",
                        "source": _text(raw.get("source")) or None,
                        "license": _text(raw.get("license")) or None,
                        "status": _text(raw.get("rights_status") or raw.get("status")) or "unknown",
                        "rights_json": _json_text(raw),
                    } for raw in raw_tracks if isinstance(raw, dict)]
                except DataSeedError as exc:
                    errors.append(f"{RIGHTS_SOURCE}: {exc}")
                else:
                    db.execute("DELETE FROM music_rights WHERE source='seed'")
                    db.executemany(
                        """INSERT INTO music_rights(track_id,title,rights_source,license,status,
                                                     rights_json,source,updated_at)
                           VALUES(?,?,?,?,?,?,'seed',?)""",
                        [(r["track_id"], r["title"], r["source"], r["license"],
                          r["status"], r["rights_json"], now) for r in rights],
                    )
                    self._record_source(db, RIGHTS_SOURCE, payload, len(rights), now)
                    sources.append({"path": RIGHTS_SOURCE, "items": len(rights)})

    def _seed_templates(self, db: sqlite3.Connection, loaded: dict[str, tuple[Any, bytes] | None],
                        sources: list[dict[str, Any]], errors: list[str], now: int) -> None:
        for relative_path, category, fallback_id, fallback_name in TEMPLATE_SOURCES:
            entry = loaded.get(relative_path)
            if entry is None:
                continue
            document, payload = entry
            if not isinstance(document, dict):
                errors.append(f"Unexpected template shape: {relative_path}")
                continue
            try:
                template = {
                    "template_id": _text(document.get("module")) or fallback_id,
                    "category": category,
                    "name": fallback_name,
                    "state": _text(document.get("state")) or "spec_only",
                    "local_only": 1 if _boolean(document.get("local_only"), default=True) else 0,
                    "spec_json": _json_text(document),
                }
            except (TypeError, ValueError) as exc:
                errors.append(f"{relative_path}: {exc}")
                continue
            db.execute(
                "DELETE FROM studio_templates WHERE source='seed' AND origin=?",
                (relative_path,),
            )
            db.execute(
                """INSERT INTO studio_templates(template_id,category,name,state,local_only,
                                                 spec_json,origin,source,updated_at)
                   VALUES(?,?,?,?,?,?,?,'seed',?)""",
                (template["template_id"], template["category"], template["name"],
                 template["state"], template["local_only"], template["spec_json"],
                 relative_path, now),
            )
            self._record_source(db, relative_path, payload, 1, now)
            sources.append({"path": relative_path, "items": 1})

    # ------------------------------------------------------------------ reads
    def _rows(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with closing(self._connect(read_only=True)) as db:
            return db.execute(query, parameters).fetchall()

    def _scalar(self, query: str, parameters: tuple[Any, ...] = (), default: Any = None) -> Any:
        with closing(self._connect(read_only=True)) as db:
            row = db.execute(query, parameters).fetchone()
        return row[0] if row else default

    def _counts(self) -> dict[str, int]:
        tables = ("gifts", "gift_rules", "like_milestones", "music_playlists",
                  "music_tracks", "music_rights", "games", "game_actions", "studio_templates")
        with closing(self._connect(read_only=True)) as db:
            return {table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in tables}

    def summary(self) -> dict[str, Any]:
        counts = self._counts()
        sources = [dict(row) for row in self._rows(
            "SELECT path,sha256,bytes,imported_at,item_count FROM catalog_sources ORDER BY path"
        )]
        meta = {row["key"]: row["value"] for row in self._rows("SELECT key,value FROM meta")}
        return {
            "ok": self._seed_report["ok"],
            "read_only": True,
            "schema_version": SCHEMA_VERSION,
            "seeded_at": self._seed_report["seeded_at"],
            "raw_data_present": self.raw_data_root.is_dir(),
            "counts": counts,
            "sources": sources,
            "errors": list(self._seed_report["errors"]),
            "import_policy": meta.get(
                "import_policy",
                "repository JSON only; legacy data/db databases are never read",
            ),
            "legacy_databases_read": False,
            "notes": [
                "Der Katalog wird aus den JSON-Rohdaten im Projekt erzeugt.",
                "Die alten data/db-Datenbanken werden nicht gelesen und nicht verändert.",
                "Es werden keine Konten, Sitzungen, Geräte oder Plattform-Zugangsdaten importiert.",
            ],
        }

    def gifts(self) -> dict[str, Any]:
        gifts = [{
            "id": row["gift_id"],
            "name": row["name"],
            "streamiov_points": int(row["streamiov_points"]),
            "tiktok_gift_id": row["tiktok_gift_id"],
            "svg": row["svg"],
            "streamiov_custom": bool(row["custom"]),
            "status": row["status"],
            "animation": row["animation"],
        } for row in self._rows("SELECT * FROM gifts ORDER BY streamiov_points, name")]
        rules = [{
            "id": row["rule_id"],
            "name": row["name"],
            "trigger": {"type": row["trigger_type"], **json.loads(row["trigger_json"])},
            "action": {"type": row["action_type"], **json.loads(row["action_json"])},
            "status": row["status"],
        } for row in self._rows("SELECT * FROM gift_rules ORDER BY name")]
        milestones = [int(row["count"]) for row in self._rows(
            "SELECT count FROM like_milestones ORDER BY count"
        )]
        meta = {row["key"]: row["value"] for row in self._rows("SELECT key,value FROM meta")}
        return {
            "ok": True,
            "read_only": True,
            "schema_version": SCHEMA_VERSION,
            "points_note": meta.get("points_note", ""),
            "gifts": gifts,
            "like_milestones": milestones,
            "rules": rules,
            "counts": {"gifts": len(gifts), "rules": len(rules), "like_milestones": len(milestones)},
            "tiktok_gift_ids_present": any(gift["tiktok_gift_id"] for gift in gifts),
            "notes": [
                "Streamiov-Punkte sind eigene lokale Werte, keine TikTok-Coins.",
                "Es ist keine TikTok-Geschenkefreigabe hinterlegt.",
                "Geschenk-Effekte bleiben lokale Vorschauen.",
            ],
        }

    def games(self) -> dict[str, Any]:
        actions_by_game: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows("SELECT * FROM game_actions ORDER BY name"):
            actions_by_game.setdefault(row["game_id"], []).append({
                "id": row["action_id"],
                "name": row["name"],
                "description": row["description"],
                "trigger_type": row["trigger_type"],
                "trigger": json.loads(row["trigger_json"]),
                "execution": json.loads(row["execution_json"]),
                "status": row["status"],
            })
        games = [{
            "game_id": row["game_id"],
            "name": row["name"],
            "version": row["version"],
            "interface_status": row["interface_status"],
            "capabilities": json.loads(row["capabilities_json"]),
            "actions": actions_by_game.get(row["game_id"], []),
        } for row in self._rows("SELECT * FROM games ORDER BY name")]
        action_count = sum(len(game["actions"]) for game in games)
        return {
            "ok": True,
            "read_only": True,
            "schema_version": SCHEMA_VERSION,
            "games": games,
            "counts": {"games": len(games), "actions": action_count},
            "notes": [
                "Nur lokal registrierte Testspiele; keine Veröffentlichung behauptet.",
                "Schnittstellenstatus stammt unverändert aus den Rohdaten.",
            ],
        }

    def music(self) -> dict[str, Any]:
        tracks_by_playlist: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows("SELECT * FROM music_tracks ORDER BY position"):
            tracks_by_playlist.setdefault(row["playlist_id"], []).append({
                "id": row["track_id"],
                "title": row["title"],
                "source": row["source"],
                "rights_status": row["rights_status"],
                "position": int(row["position"]),
            })
        playlists = [{
            "id": row["playlist_id"],
            "streamer_id": row["streamer_id"],
            "name": row["name"],
            "active": bool(row["active"]),
            "volume": float(row["volume"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "tracks": tracks_by_playlist.get(row["playlist_id"], []),
        } for row in self._rows("SELECT * FROM music_playlists ORDER BY name")]
        rights = [{
            "id": row["track_id"],
            "title": row["title"],
            "source": row["rights_source"],
            "license": row["license"],
            "status": row["status"],
        } for row in self._rows("SELECT * FROM music_rights ORDER BY title")]
        return {
            "ok": True,
            "read_only": True,
            "schema_version": SCHEMA_VERSION,
            "playlists": playlists,
            "rights_tracks": rights,
            "counts": {
                "playlists": len(playlists),
                "tracks": sum(len(playlist["tracks"]) for playlist in playlists),
                "rights_tracks": len(rights),
            },
            "notes": [
                "Wiedergabe erfolgt ausschließlich lokal.",
                "Rechteangaben stammen unverändert aus den Rohdaten; keine Lizenzprüfung.",
            ],
        }

    def templates(self) -> dict[str, Any]:
        templates = [{
            "id": row["template_id"],
            "category": row["category"],
            "name": row["name"],
            "state": row["state"],
            "local_only": bool(row["local_only"]),
            "spec": json.loads(row["spec_json"]),
        } for row in self._rows("SELECT * FROM studio_templates ORDER BY category, name")]
        return {
            "ok": True,
            "read_only": True,
            "schema_version": SCHEMA_VERSION,
            "templates": templates,
            "counts": {"templates": len(templates)},
            "notes": [
                "Vorlagen sind lokale Spezifikationen und keine installierten Funktionen.",
                "Statuswerte werden unverändert aus den Rohdaten übernommen.",
            ],
        }

    def catalog(self, kind: str) -> dict[str, Any]:
        if kind not in CATALOG_KINDS:
            raise KeyError(kind)
        return {
            "summary": self.summary,
            "gifts": self.gifts,
            "games": self.games,
            "music": self.music,
            "templates": self.templates,
        }[kind]()
