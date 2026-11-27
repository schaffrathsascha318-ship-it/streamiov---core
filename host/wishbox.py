"""Durable, fail-closed Wunschbox order centre for music and game requests."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
import uuid


ORDER_ID_PATTERN = re.compile(r"^wish-[a-f0-9]{32}$")
ORDER_STATUSES = frozenset({
    "received", "reviewed", "queued", "assigned", "in_progress",
    "completed", "rejected", "clarification_needed",
})
ORDER_KINDS = frozenset({"music", "game", "unknown"})
PRIORITIES = frozenset({"low", "normal", "high"})
MAX_TEXT = 1200
MIN_TEXT = 3
MAX_RESULT = 2000
TERRITORY_PATTERN = re.compile(r"^[A-Z]{2}$")

GAME_NAMES = (
    "neon-relay", "echo-grid", "pulse-defender", "minecraft", "fortnite",
    "valorant", "counter-strike", "counter strike", "cs2", "league of legends",
    "gta v", "grand theft auto", "roblox", "overwatch", "rocket league",
    "elden ring", "mario kart", "tetris", "among us", "diablo", "cyberpunk",
    "call of duty", "apex legends", "fifa", "fc 25", "subway surfers",
)
MUSIC_MARKERS = (
    "song", "lied", "track", "musik", "playlist", "titel", "artist", "interpret",
    "album", "audio", "spotify", "remix", "intro", "outro",
)
GAME_MARKERS = (
    "spiel", "zock", "runde", "challenge", "herausforderung", "highscore",
    "replay", "gegame", "gezockt", "gegner", "boss", "level", "taktik",
    "strategie", "situation", "gameplay", "streamer",
)
DISALLOWED_PATTERN = re.compile(
    r"\b(cheat|cheats|hack|hacks|aimbot|wallhack|wall.?hack|bott?|bots|"
    r"mod.?menu|autoklick|auto.?klick|auto.?play|auto.?input|"
    r"script.?klick|macro|makro|duplizier|free.?money|geld.?hack|"
    r"unlimited|insta.?kill|exploit|alter.?mann|kind|minor)\b",
    re.IGNORECASE,
)
CHALLENGE_PATTERN = re.compile(
    r"challenge|herausforderung|rekord|speedrun|highscore|bestzeit|aufgabe|quest", re.IGNORECASE)
ANALYSIS_PATTERN = re.compile(
    r"analys|erklär|erklaer|einschätz|einschaetz|bewert|situation|warum|wie.?spiel|"
    r"taktik|strategie|feedback|verbesser", re.IGNORECASE)
QUESTION_PATTERN = re.compile(r"\?|^was\b|^wie\b|^warum\b|^welche", re.IGNORECASE)
ACTION_PATTERN = re.compile(
    r"\b(mach|spring|schieß|schiess|lauf|dreh|wähle|waehle|test|versuch|"
    r"zeig|klopf|interagier|sammel|fahr)\b", re.IGNORECASE)


class WishboxError(ValueError):
    """Safe-to-return Wunschbox validation or state error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalise(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w\s-]", " ", text).split())


def validate_text(value: object) -> str:
    if not isinstance(value, str):
        raise WishboxError("Auftragstext muss Text sein.")
    text = " ".join(value.split())
    if not MIN_TEXT <= len(text) <= MAX_TEXT or "\x00" in text:
        raise WishboxError(f"Auftragstext muss {MIN_TEXT} bis {MAX_TEXT} Zeichen lang sein.")
    return text


def validate_territory(value: object) -> str:
    territory = value if isinstance(value, str) else ""
    territory = territory.strip().upper()
    if not TERRITORY_PATTERN.fullmatch(territory):
        raise WishboxError("Territorium muss ein zweistelliger Ländercode sein.")
    return territory


def classify(text: object) -> dict:
    clean = validate_text(text)
    folded = _normalise(clean)
    words = set(folded.split())
    game = next((name for name in GAME_NAMES
                 if _normalise(name).replace("-", " ") in folded.replace("-", " ")), "")
    music_hits = len(words & {_normalise(word) for word in MUSIC_MARKERS})
    music_hits += sum(1 for word in MUSIC_MARKERS if " " in word and word in folded)
    game_hits = len(words & {_normalise(word) for word in GAME_MARKERS})
    game_hits += sum(1 for word in GAME_MARKERS if " " in word and word in folded)
    title, artist = _parse_music(clean)
    if game and (game_hits or not music_hits):
        kind = "game"
    elif music_hits > game_hits:
        kind = "music"
    elif game_hits:
        kind = "game"
    elif title and artist:
        kind = "music"
    else:
        kind = "unknown"
    intent = "unknown"
    if kind == "music":
        intent = "playlist" if "playlist" in folded else "song_request"
    elif kind == "game":
        if ANALYSIS_PATTERN.search(clean):
            intent = "analysis"
        elif CHALLENGE_PATTERN.search(clean):
            intent = "challenge"
        elif QUESTION_PATTERN.search(clean):
            intent = "question"
        elif ACTION_PATTERN.search(clean):
            intent = "game_action"
        else:
            intent = "game_request"
    disallowed = bool(DISALLOWED_PATTERN.search(clean))
    return {
        "kind": kind,
        "intent": intent,
        "game": game,
        "title": title,
        "artist": artist,
        "disallowed": disallowed,
        "feasible": kind in {"music", "game"} and not disallowed,
    }


def _parse_music(text: str) -> tuple[str, str]:
    dash = re.split(r"\s+[-–—]\s+", text, maxsplit=1)
    if len(dash) == 2 and dash[0].strip() and dash[1].strip():
        return dash[0].strip()[:160], dash[1].strip()[:160]
    match = re.search(
        r"\b(?:spiel|spiele|play|put|füge|add)\s+(?:mir\s+|uns\s+)?"
        r"(?:den|das|die|the)?\s*(?P<title>.+?)\s+(?:von|by|des)\s+(?P<artist>.+)$",
        text, re.IGNORECASE,
    )
    if match:
        return match.group("title").strip()[:160], match.group("artist").strip()[:160]
    return "", ""


def _track_matches(track: dict, title: str, artist: str) -> bool:
    candidate_title = _normalise(track.get("title"))
    candidate_artist = _normalise(track.get("artist"))
    wanted_title = _normalise(title)
    wanted_artist = _normalise(artist)
    if not candidate_title:
        return False
    title_ok = bool(wanted_title and (
        wanted_title in candidate_title or candidate_title in wanted_title
        or _similar(wanted_title, candidate_title)))
    if not title_ok:
        return False
    if not wanted_artist or not candidate_artist:
        return True
    return bool(wanted_artist in candidate_artist or candidate_artist in wanted_artist
                or _similar(wanted_artist, candidate_artist))


def _similar(left: str, right: str) -> bool:
    if len(left) < 4 or len(right) < 4:
        return False
    return left in right or right in left or len(set(left) & set(right)) >= max(4, min(len(left), len(right)) // 2)


class WishboxStore:
    """SQLite-backed order lifecycle with an owner-scoped audit trail."""

    def __init__(self, data_dir: str | Path, *, music_catalog=None, event_publisher=None):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self.database = self.data_dir / "wishbox.sqlite3"
        self.music_catalog = music_catalog
        self.event_publisher = event_publisher
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
                CREATE TABLE IF NOT EXISTS wish_orders (
                    order_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    source TEXT NOT NULL,
                    game TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    description TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    result TEXT NOT NULL,
                    feedback TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    handoff_json TEXT NOT NULL,
                    territory TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS wish_orders_owner_created
                    ON wish_orders(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS wish_orders_dedupe
                    ON wish_orders(user_id, dedupe_key, status);
                CREATE TABLE IF NOT EXISTS wish_history (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL REFERENCES wish_orders(order_id) ON DELETE CASCADE,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS wish_history_order ON wish_history(order_id, entry_id);
            """)
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict:
        try:
            handoff = json.loads(row["handoff_json"]) if row["handoff_json"] else {}
        except (TypeError, ValueError):
            handoff = {}
        if not isinstance(handoff, dict):
            handoff = {}
        return {
            "id": row["order_id"],
            "kind": row["kind"],
            "intent": row["intent"],
            "sender": row["sender"],
            "source": row["source"],
            "game": row["game"],
            "title": row["title"],
            "artist": row["artist"],
            "description": row["description"],
            "priority": row["priority"],
            "status": row["status"],
            "agent": row["agent"],
            "result": row["result"],
            "feedback": row["feedback"],
            "territory": row["territory"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "handoff": handoff,
        }

    def _history(self, order_id: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT from_status, to_status, actor, note, created_at "
                "FROM wish_history WHERE order_id = ? ORDER BY entry_id",
                (order_id,),
            ).fetchall()
        return [{
            "from": row["from_status"], "to": row["to_status"], "actor": row["actor"],
            "note": row["note"][:240], "created_at": row["created_at"],
        } for row in rows]

    def detail(self, order_id: object, user_id: object) -> dict | None:
        if not isinstance(order_id, str) or not ORDER_ID_PATTERN.fullmatch(order_id):
            return None
        if not isinstance(user_id, str) or not user_id:
            return None
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM wish_orders WHERE order_id = ? AND user_id = ?",
                (order_id, user_id),
            ).fetchone()
        if row is None:
            return None
        payload = self._payload(row)
        payload["history"] = self._history(order_id)
        return payload

    def list_orders(self, user_id: object, *, limit: int = 50, kind: str | None = None) -> list[dict]:
        if not isinstance(user_id, str) or not user_id:
            raise WishboxError("Anmeldung erforderlich.")
        bounded = max(1, min(int(limit), 100))
        query = "SELECT * FROM wish_orders WHERE user_id = ?"
        params: list = [user_id]
        if kind in ORDER_KINDS:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(bounded)
        with closing(self._connect()) as db:
            rows = db.execute(query, params).fetchall()
        return [self._payload(row) for row in rows]

    def handoffs(self, user_id: object, *, limit: int = 50) -> list[dict]:
        orders = self.list_orders(user_id, limit=max(limit * 4, 50), kind="game")
        return [order for order in orders
                if order["status"] in {"assigned", "in_progress"} and order["handoff"]]

    def _publish(self, user_id: str, event_type: str, order: dict) -> bool:
        if self.event_publisher is None:
            return True
        try:
            self.event_publisher(user_id, event_type, {
                "order_id": order["id"],
                "kind": order["kind"],
                "status": order["status"],
                "agent": order["agent"],
                "game": order["game"],
                "intent": order["intent"],
            })
            return True
        except Exception:
            return False

    def _append_history(self, db: sqlite3.Connection, order_id: str,
                        from_status: str, to_status: str, actor: str, note: str) -> None:
        db.execute(
            "INSERT INTO wish_history(order_id, from_status, to_status, actor, note, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (order_id, from_status, to_status, actor[:80], note[:240], _utc_now()),
        )

    def _set_status(self, db: sqlite3.Connection, order_id: str, user_id: str,
                    status: str, actor: str, note: str) -> None:
        row = db.execute(
            "SELECT status FROM wish_orders WHERE order_id = ? AND user_id = ?",
            (order_id, user_id),
        ).fetchone()
        if row is None:
            raise WishboxError("Auftrag nicht gefunden.")
        previous = row["status"]
        db.execute(
            "UPDATE wish_orders SET status = ?, updated_at = ? WHERE order_id = ? AND user_id = ?",
            (status, _utc_now(), order_id, user_id),
        )
        self._append_history(db, order_id, previous, status, actor, note)

    def submit(self, user_id: object, text: object, *, sender: object = "viewer",
               source: object = "chat", territory: object = "DE",
               priority: object = "normal") -> dict:
        if not isinstance(user_id, str) or not user_id:
            raise WishboxError("Anmeldung erforderlich.")
        clean = validate_text(text)
        clean_sender = " ".join(str(sender or "viewer").split())[:80] or "viewer"
        clean_source = " ".join(str(source or "chat").split())[:40] or "chat"
        clean_territory = validate_territory(territory)
        clean_priority = priority if isinstance(priority, str) and priority in PRIORITIES else "normal"
        verdict = classify(clean)
        dedupe_key = f"{verdict['kind']}|{_normalise(verdict['title'] or clean)}|" \
                     f"{_normalise(verdict['artist'])}|{verdict['game']}"
        order_id = "wish-" + uuid.uuid4().hex
        now = _utc_now()
        with self._transaction() as db:
            duplicate = db.execute(
                "SELECT * FROM wish_orders WHERE user_id = ? AND dedupe_key = ? "
                "AND status NOT IN ('rejected', 'completed') ORDER BY created_at DESC LIMIT 1",
                (user_id, dedupe_key),
            ).fetchone()
            if duplicate is not None:
                payload = self._payload(duplicate)
                payload["duplicate"] = True
                return payload
            db.execute("""
                INSERT INTO wish_orders(
                    order_id, user_id, kind, intent, sender, source, game, title,
                    artist, description, priority, status, agent, result, feedback,
                    dedupe_key, handoff_json, territory, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'received','','','',?,?,?,?,?)
            """, (
                order_id, user_id, verdict["kind"], verdict["intent"], clean_sender,
                clean_source, verdict["game"], verdict["title"], verdict["artist"],
                clean, clean_priority, dedupe_key, "", clean_territory, now, now,
            ))
            self._append_history(db, order_id, "", "received", clean_sender, "Auftrag eingegangen")
            self._set_status(db, order_id, user_id, "reviewed", "wunschbox-ki", "Auftrag geprüft")
            order = self._decide(db, order_id, user_id, verdict, clean_territory, clean)
        self._publish(user_id, "wishbox.order.received", order)
        self._publish(user_id, "wishbox.order.status", order)
        return order

    def _decide(self, db: sqlite3.Connection, order_id: str, user_id: str, verdict: dict,
                territory: str, description: str) -> dict:
        if verdict["disallowed"]:
            self._set_status(db, order_id, user_id, "rejected", "wunschbox-ki", "unzulässige Aktion")
            feedback = ("Ich kann keine Cheats, Bots oder automatisierten Spieleingriffe ausführen. "
                        "Der Streamer behält die Kontrolle; ich darf nur Vorschläge liefern.")
            db.execute("UPDATE wish_orders SET feedback = ? WHERE order_id = ?", (feedback, order_id))
        elif verdict["kind"] == "game" and not verdict["game"]:
            self._set_status(db, order_id, user_id, "clarification_needed", "wunschbox-ki",
                             "Spiel unklar")
            feedback = "Für welchen Titel soll der Auftrag gelten? Nenne bitte das Spiel."
            db.execute("UPDATE wish_orders SET feedback = ? WHERE order_id = ?", (feedback, order_id))
        elif verdict["kind"] == "unknown":
            self._set_status(db, order_id, user_id, "clarification_needed", "wunschbox-ki",
                             "Typ unklar")
            feedback = ("Ist das ein Musikwunsch oder ein Spielauftrag? "
                        "Nenne bei Musik Titel und Interpret, bei Spielen den Titel.")
            db.execute("UPDATE wish_orders SET feedback = ? WHERE order_id = ?", (feedback, order_id))
        elif verdict["kind"] == "music":
            track = self._find_track(verdict, territory)
            if track is None:
                self._set_status(db, order_id, user_id, "rejected", "wunschbox-ki",
                                 "keine LIVE-Freigabe")
                feedback = ("Diesen Titel gibt es nicht in der für LIVE freigegebenen lokalen "
                            "Bibliothek. Ich spiele nichts ohne geprüfte Rechte ab.")
                db.execute("UPDATE wish_orders SET feedback = ? WHERE order_id = ?", (feedback, order_id))
            else:
                self._set_status(db, order_id, user_id, "queued", "wunschbox-ki", "Musikwarteschlange")
                handoff = {
                    "agent": "music",
                    "track_id": track["id"],
                    "title": track["title"],
                    "artist": track["artist"],
                    "territory": territory,
                    "usage": "live_stream",
                    "source": "approved_local_catalogue",
                    "constraints": ["rights_approved", "local_audio_only", "studio_mixer"],
                }
                db.execute(
                    "UPDATE wish_orders SET agent = ?, handoff_json = ?, feedback = ? WHERE order_id = ?",
                    ("music", json.dumps(handoff, ensure_ascii=False),
                     f"Musikwunsch «{track['title']}» ist in der LIVE-Bibliothek freigegeben und wartet in der Warteschlange.",
                     order_id),
                )
        else:
            self._set_status(db, order_id, user_id, "queued", "wunschbox-ki", "Spielewarteschlange")
            handoff = {
                "agent": "gaming",
                "game": verdict["game"],
                "intent": verdict["intent"],
                "description": description[:500],
                "constraints": ["advisory_only", "no_cheats", "no_game_input", "streamer_control"],
            }
            db.execute(
                "UPDATE wish_orders SET agent = ?, handoff_json = ?, feedback = ? WHERE order_id = ?",
                ("gaming", json.dumps(handoff, ensure_ascii=False),
                 f"Spielauftrag «{verdict['game']}» wurde geprüft und an die Gaming-KI übergeben. "
                 "Der Streamer entscheidet, was umgesetzt wird.", order_id),
            )
        row = db.execute("SELECT * FROM wish_orders WHERE order_id = ?", (order_id,)).fetchone()
        return self._payload(row)

    def _find_track(self, verdict: dict, territory: str) -> dict | None:
        if self.music_catalog is None:
            return None
        try:
            tracks = self.music_catalog.gate(territory, "live_stream")["tracks"]
        except Exception:
            return None
        for track in tracks:
            if track.get("allowed") is True and _track_matches(track, verdict["title"], verdict["artist"]):
                return track
        return None

    def dispatch(self, order_id: object, user_id: object) -> dict:
        return self._transition(order_id, user_id, "dispatch", "wunschbox-ki")

    def claim(self, order_id: object, user_id: object, agent: object = "gaming") -> dict:
        return self._transition(order_id, user_id, "claim", agent)

    def reject(self, order_id: object, user_id: object, reason: object = "") -> dict:
        return self._transition(order_id, user_id, "reject", user_id, note=reason)

    def clarify(self, order_id: object, user_id: object, answer: object) -> dict:
        return self._transition(order_id, user_id, "clarify", user_id, note=answer)

    def complete(self, order_id: object, user_id: object, result: object, *, agent: object = "gaming") -> dict:
        return self._transition(order_id, user_id, "complete", agent, note=result)

    def _transition(self, order_id: object, user_id: object, action: str,
                    actor: object, note: object = "") -> dict:
        if not isinstance(user_id, str) or not user_id:
            raise WishboxError("Anmeldung erforderlich.")
        if not isinstance(order_id, str) or not ORDER_ID_PATTERN.fullmatch(order_id):
            raise WishboxError("Ungültige Auftrags-ID.")
        actor_name = " ".join(str(actor or "agent").split())[:80] or "agent"
        detail = " ".join(str(note or "").split())[:MAX_RESULT]
        allowed = {
            "dispatch": {"queued"},
            "claim": {"assigned"},
            "reject": {"received", "reviewed", "queued", "assigned", "in_progress", "clarification_needed"},
            "clarify": {"clarification_needed"},
            "complete": {"in_progress"},
        }[action]
        with self._transaction() as db:
            row = db.execute(
                "SELECT * FROM wish_orders WHERE order_id = ? AND user_id = ?",
                (order_id, user_id),
            ).fetchone()
            if row is None:
                raise WishboxError("Auftrag nicht gefunden.")
            if row["status"] not in allowed:
                raise WishboxError(f"Übergang aus Status {row['status']} nicht erlaubt.")
            payload = self._payload(row)
            if action == "dispatch":
                self._set_status(db, order_id, user_id, "assigned", actor_name, "Agent zugewiesen")
                feedback = (f"Auftrag an {row['agent']} übergeben. "
                            "Es werden keine Spieleingriffe ohne Streamerfreigabe ausgeführt.")
                db.execute("UPDATE wish_orders SET feedback = ? WHERE order_id = ?", (feedback, order_id))
            elif action == "claim":
                self._set_status(db, order_id, user_id, "in_progress", actor_name, "Bearbeitung begonnen")
                db.execute("UPDATE wish_orders SET agent = ?, feedback = ? WHERE order_id = ?",
                           (actor_name, "Auftrag wird bearbeitet.", order_id))
            elif action == "reject":
                if not detail:
                    detail = "Vom Streamer abgelehnt"
                self._set_status(db, order_id, user_id, "rejected", actor_name, detail)
                db.execute("UPDATE wish_orders SET feedback = ?, handoff_json = '' WHERE order_id = ?",
                           (f"Auftrag abgelehnt: {detail}", order_id))
            elif action == "clarify":
                if not detail:
                    raise WishboxError("Rückfrage benötigt eine Antwort.")
                verdict = classify(f"{row['description']} {detail}")
                self._set_status(db, order_id, user_id, "reviewed", actor_name, detail)
                db.execute(
                    "UPDATE wish_orders SET description = ?, game = ?, kind = ?, intent = ?, "
                    "agent = '', handoff_json = '' WHERE order_id = ?",
                    (f"{row['description']} {detail}"[:MAX_TEXT], verdict["game"],
                     verdict["kind"], verdict["intent"], order_id),
                )
                self._decide(db, order_id, user_id, verdict, row["territory"],
                             f"{row['description']} {detail}")
            else:
                if not detail:
                    raise WishboxError("Ergebnis darf nicht leer sein.")
                self._set_status(db, order_id, user_id, "completed", actor_name, detail)
                db.execute(
                    "UPDATE wish_orders SET result = ?, feedback = ?, handoff_json = '' WHERE order_id = ?",
                    (detail, f"Ergebnis: {detail}", order_id),
                )
            updated = db.execute("SELECT * FROM wish_orders WHERE order_id = ?", (order_id,)).fetchone()
            result = self._payload(updated)
        self._publish(user_id, "wishbox.order.status", result)
        if action == "complete":
            self._publish(user_id, "wishbox.order.result", result)
        return result
