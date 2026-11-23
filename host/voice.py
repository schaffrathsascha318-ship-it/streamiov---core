"""Authenticated, persistent Voice rooms and short-lived signalling tokens.

The host issues room-scoped HMAC tokens only after checking the account session
and persistent membership. The signing key is supplied by runtime configuration;
it is never stored in SQLite or returned to clients.
"""
from __future__ import annotations

import base64
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid


TOKEN_TTL_SECONDS = 300
MAX_ROOM_NAME = 64
MAX_INVITE_TTL = 24 * 60 * 60
MAX_INVITE_USES = 20
MAX_OPEN_ROOMS_PER_OWNER = 5
MAX_ACTIVE_INVITES_PER_ROOM = 20
MAX_ROOM_MEMBERS = 32


class VoiceError(ValueError):
    """Safe-to-return room, invite, or configuration error."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signing_key() -> bytes:
    raw = os.environ.get("STREAMIOV_VOICE_SIGNING_KEY", "")
    if len(raw.encode("utf-8")) < 32:
        raise VoiceError("Voice-Signaturschlüssel ist nicht konfiguriert (mindestens 32 Byte).")
    return raw.encode("utf-8")


def voice_ice_configuration(user_id: str, *, now: int | None = None) -> dict:
    """Return public STUN plus short-lived coturn REST credentials when configured."""
    current = int(time.time()) if now is None else int(now)
    raw_urls = os.environ.get("STREAMIOV_TURN_URLS", "")
    urls = [item.strip() for item in raw_urls.split(",") if item.strip()]
    urls = [item for item in urls if item.startswith(("turn:", "turns:")) and len(item) <= 512 and not any(ch.isspace() for ch in item)]
    secret = os.environ.get("STREAMIOV_TURN_SHARED_SECRET", "")
    result = [{"urls": "stun:stun.l.google.com:19302"}]
    if urls and len(secret.encode("utf-8")) >= 32:
        expiry = current + 3600
        username = f"{expiry}:{user_id}"
        credential = base64.b64encode(
            hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()
        ).decode("ascii")
        result.insert(0, {"urls": urls, "username": username, "credential": credential})
    return {"ice_servers": result, "turn_available": bool(urls and len(secret.encode("utf-8")) >= 32)}


def issue_voice_token(*, user_id: str, room_id: str, role: str, now: int | None = None) -> dict:
    current = int(time.time()) if now is None else int(now)
    if role not in {"owner", "moderator", "member", "guest"}:
        raise VoiceError("Ungültige Voice-Rolle.")
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": "streamiov-core",
        "aud": "streamiov-voice",
        "sub": user_id,
        "room": room_id,
        "role": role,
        "iat": current,
        "nbf": current - 2,
        "exp": current + TOKEN_TTL_SECONDS,
        "jti": secrets.token_urlsafe(18),
    }
    encoded = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded += "." + _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(_signing_key(), encoded.encode("ascii"), hashlib.sha256).digest()
    return {"token": encoded + "." + _b64url(signature), "expires_in": TOKEN_TTL_SECONDS, "token_type": "Bearer"}


class VoiceRoomStore:
    """SQLite-backed rooms, one-time invite codes and membership roles."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.data_dir / "voice-rooms.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def _db(self):
        with closing(self._connect()) as db:
            with db:
                yield db

    def _initialize(self) -> None:
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS voice_rooms(
                    room_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    closed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS voice_members(
                    room_id TEXT NOT NULL REFERENCES voice_rooms(room_id),
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('owner','moderator','member','guest')),
                    joined_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    PRIMARY KEY(room_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS voice_invites(
                    invite_hash BLOB PRIMARY KEY,
                    room_id TEXT NOT NULL REFERENCES voice_rooms(room_id),
                    created_by TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('moderator','member','guest')),
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL,
                    uses INTEGER NOT NULL DEFAULT 0,
                    revoked_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS voice_invites_room ON voice_invites(room_id);
                CREATE INDEX IF NOT EXISTS voice_members_user ON voice_members(user_id,revoked_at);
            """)
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @staticmethod
    def _hash_invite(code: str) -> bytes:
        return hashlib.sha256(code.encode("ascii")).digest()

    @staticmethod
    def _new_invite(db: sqlite3.Connection, room_id: str, created_by: str,
                    role: str, ttl: int, max_uses: int, now: int) -> str:
        code = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO voice_invites(invite_hash,room_id,created_by,role,created_at,expires_at,max_uses) VALUES(?,?,?,?,?,?,?)",
            (VoiceRoomStore._hash_invite(code), room_id, created_by, role, now, now + ttl, max_uses),
        )
        return code

    def create_room(self, owner_id: str, name: object, *, now: int | None = None) -> dict:
        clean = " ".join(str(name or "").split())
        if not 1 <= len(clean) <= MAX_ROOM_NAME:
            raise VoiceError("Raumname muss 1–64 Zeichen lang sein.")
        current = int(time.time()) if now is None else int(now)
        room_id = uuid.uuid4().hex
        with self._db() as db:
            # Serialize quota check + insert across concurrent Core request threads.
            db.execute("BEGIN IMMEDIATE")
            open_rooms = db.execute(
                "SELECT COUNT(*) FROM voice_rooms WHERE owner_id=? AND closed_at IS NULL",
                (owner_id,),
            ).fetchone()[0]
            if open_rooms >= MAX_OPEN_ROOMS_PER_OWNER:
                raise VoiceError("Ein Eigentümer darf höchstens fünf offene Voice-Räume haben.")
            db.execute("INSERT INTO voice_rooms(room_id,name,owner_id,created_at) VALUES(?,?,?,?)",
                       (room_id, clean, owner_id, current))
            db.execute("INSERT INTO voice_members(room_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                       (room_id, owner_id, "owner", current))
            invite = self._new_invite(db, room_id, owner_id, "guest", MAX_INVITE_TTL, 8, current)
        return {"room_id": room_id, "name": clean, "role": "owner", "invite_code": invite,
                "invite_expires_in": MAX_INVITE_TTL, "invite_max_uses": 8}

    def create_invite(self, owner_id: str, room_id: str, *, role: str = "guest",
                      ttl: int = 3600, max_uses: int = 1, now: int | None = None) -> dict:
        if role not in {"moderator", "member", "guest"}:
            raise VoiceError("Ungültige Einladungsrolle.")
        if type(ttl) is not int or not 60 <= ttl <= MAX_INVITE_TTL:
            raise VoiceError("Einladung muss 60–86400 Sekunden gültig sein.")
        if type(max_uses) is not int or not 1 <= max_uses <= MAX_INVITE_USES:
            raise VoiceError("Einladung darf 1–20 Verwendungen haben.")
        current = int(time.time()) if now is None else int(now)
        with self._db() as db:
            # Prevent concurrent invite requests from exceeding the active-invite cap.
            db.execute("BEGIN IMMEDIATE")
            room = db.execute("SELECT owner_id,closed_at FROM voice_rooms WHERE room_id=?", (room_id,)).fetchone()
            if room is None or room["closed_at"] is not None:
                raise VoiceError("Voice-Raum nicht gefunden oder geschlossen.")
            member = db.execute("SELECT role,revoked_at FROM voice_members WHERE room_id=? AND user_id=?",
                                (room_id, owner_id)).fetchone()
            if room["owner_id"] != owner_id or member is None or member["revoked_at"] is not None:
                raise VoiceError("Nur der Raumeigentümer darf Einladungen erstellen.")
            active_invites = db.execute(
                "SELECT COUNT(*) FROM voice_invites WHERE room_id=? AND revoked_at IS NULL AND expires_at>? AND uses<max_uses",
                (room_id, current),
            ).fetchone()[0]
            if active_invites >= MAX_ACTIVE_INVITES_PER_ROOM:
                raise VoiceError("Für diesen Raum sind bereits 20 aktive Einladungen vorhanden.")
            code = self._new_invite(db, room_id, owner_id, role, ttl, max_uses, current)
        return {"invite_code": code, "role": role, "expires_in": ttl, "max_uses": max_uses}

    def join(self, user_id: str, invite_code: object, *, now: int | None = None) -> dict:
        if not isinstance(invite_code, str) or not 32 <= len(invite_code) <= 64:
            raise VoiceError("Einladung ist ungültig oder abgelaufen.")
        try:
            invite_hash = self._hash_invite(invite_code)
        except UnicodeEncodeError as exc:
            raise VoiceError("Einladung ist ungültig oder abgelaufen.") from exc
        current = int(time.time()) if now is None else int(now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            invite = db.execute("""
                SELECT i.room_id,i.role,i.expires_at,i.max_uses,i.uses,r.name,r.closed_at,r.owner_id
                FROM voice_invites i JOIN voice_rooms r USING(room_id)
                WHERE i.invite_hash=? AND i.revoked_at IS NULL
            """, (invite_hash,)).fetchone()
            if (invite is None or invite["closed_at"] is not None or invite["expires_at"] <= current
                    or invite["uses"] >= invite["max_uses"]):
                raise VoiceError("Einladung ist ungültig, abgelaufen oder bereits verwendet.")
            if user_id == invite["owner_id"]:
                return {"room_id": invite["room_id"], "name": invite["name"], "role": "owner"}
            existing = db.execute(
                "SELECT role FROM voice_members WHERE room_id=? AND user_id=? AND revoked_at IS NULL",
                (invite["room_id"], user_id),
            ).fetchone()
            if existing:
                return {"room_id": invite["room_id"], "name": invite["name"], "role": existing["role"]}
            member_count = db.execute(
                "SELECT COUNT(*) FROM voice_members WHERE room_id=? AND revoked_at IS NULL",
                (invite["room_id"],),
            ).fetchone()[0]
            if member_count >= MAX_ROOM_MEMBERS:
                raise VoiceError("Voice-Raum hat die maximale Mitgliederzahl erreicht.")
            db.execute("UPDATE voice_invites SET uses=uses+1 WHERE invite_hash=? AND uses<max_uses",
                       (invite_hash,))
            db.execute("""
                INSERT INTO voice_members(room_id,user_id,role,joined_at,revoked_at)
                VALUES(?,?,?,?,NULL)
                ON CONFLICT(room_id,user_id) DO UPDATE SET role=excluded.role,joined_at=excluded.joined_at,revoked_at=NULL
            """, (invite["room_id"], user_id, invite["role"], current))
            return {"room_id": invite["room_id"], "name": invite["name"], "role": invite["role"]}

    def role_for(self, user_id: str, room_id: str) -> str | None:
        with self._db() as db:
            row = db.execute("""
                SELECT m.role FROM voice_members m JOIN voice_rooms r USING(room_id)
                WHERE m.user_id=? AND m.room_id=? AND m.revoked_at IS NULL AND r.closed_at IS NULL
            """, (user_id, room_id)).fetchone()
        return row["role"] if row else None

    def close_room(self, owner_id: str, room_id: str, *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        with self._db() as db:
            result = db.execute("UPDATE voice_rooms SET closed_at=? WHERE room_id=? AND owner_id=? AND closed_at IS NULL",
                                (current, room_id, owner_id))
            if result.rowcount:
                db.execute("UPDATE voice_invites SET revoked_at=? WHERE room_id=? AND revoked_at IS NULL",
                           (current, room_id))
                db.execute("UPDATE voice_members SET revoked_at=? WHERE room_id=? AND revoked_at IS NULL",
                           (current, room_id))
            return result.rowcount == 1

    def issue_member_token(self, user_id: str, room_id: str) -> dict:
        role = self.role_for(user_id, room_id)
        if role is None:
            raise VoiceError("Keine aktive Mitgliedschaft in diesem Voice-Raum.")
        token = issue_voice_token(user_id=user_id, room_id=room_id, role=role)
        token.update({"room_id": room_id, "role": role})
        return token
