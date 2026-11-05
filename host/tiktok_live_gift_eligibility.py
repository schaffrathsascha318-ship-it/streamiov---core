"""Default-deny country gate for the future official TikTok LIVE gift path.

This module does not connect to TikTok and does not create approvals. Only an
operator-controlled record backed by written TikTok evidence can enable a
country. Callers must supply a country claim obtained from a verified TikTok
account response; never derive it from IP address, locale, language, or UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import sqlite3
from pathlib import Path
from typing import Any

SCOPE = "tiktok_live_gifts"
# ISO 3166-1 alpha-2 assigned codes (including officially assigned special
# entries used in country-code datasets; user input is still normalized strictly).
ISO_ALPHA2 = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
DE DJ DK DM DO DZ
EC EE EG EH ER ES ET
FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
HK HM HN HR HT HU
ID IE IL IM IN IO IQ IR IS IT
JE JM JO JP
KE KG KH KI KM KN KP KR KW KY KZ
LA LB LC LI LK LR LS LT LU LV LY
MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
NA NC NE NF NG NI NL NO NP NR NU NZ
OM
PA PE PF PG PH PK PL PM PN PR PS PT PW PY
QA
RE RO RS RU RW
SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ
TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ
UA UG UM US UY UZ
VA VC VE VG VI VN VU
WF WS
YE YT
ZA ZM ZW
""".split())
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Timestamp must be a non-empty ISO-8601 string.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    return current.astimezone(timezone.utc)


@dataclass(frozen=True)
class EligibilityDecision:
    allowed: bool
    reason: str
    country_code: str | None = None
    scope: str = SCOPE


class TikTokLiveGiftEligibility:
    """SQLite-backed approval registry and audit log; default deny."""

    def __init__(self, database: str | Path):
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tiktok_live_gift_country_approvals (
                    country_code TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tiktok_live_gift_country_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    action TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    @staticmethod
    def _country(code: Any) -> str:
        if not isinstance(code, str):
            raise ValueError("Country code must be ISO 3166-1 alpha-2 text.")
        normalized = code.upper()
        if not COUNTRY_RE.fullmatch(normalized) or normalized not in ISO_ALPHA2:
            raise ValueError("Country code is not an assigned ISO 3166-1 alpha-2 code.")
        return normalized

    def set_approval(
        self, *, country_code: str, evidence_ref: str, confirmed_at: str,
        expires_at: str | None = None, status: str = "approved",
        scope: str = SCOPE, now: datetime | None = None,
    ) -> None:
        country = self._country(country_code)
        if scope != SCOPE:
            raise ValueError("Approval scope must be exactly tiktok_live_gifts.")
        if status not in {"approved", "denied", "revoked"}:
            raise ValueError("Unsupported approval status.")
        if not isinstance(evidence_ref, str) or not evidence_ref.strip() or len(evidence_ref) > 500:
            raise ValueError("A durable written TikTok evidence reference is required.")
        confirmed = _utc(confirmed_at)
        expiry = _utc(expires_at)
        current = _now(now)
        if confirmed is None or confirmed > current:
            raise ValueError("Confirmation must not be in the future.")
        if expiry is not None and expiry <= confirmed:
            raise ValueError("Expiry must be later than confirmation.")
        revoked_at = current.isoformat() if status == "revoked" else None
        with self._connect() as db:
            db.execute("""
                INSERT INTO tiktok_live_gift_country_approvals
                (country_code, scope, status, evidence_ref, confirmed_at, expires_at, revoked_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(country_code) DO UPDATE SET
                  scope=excluded.scope, status=excluded.status,
                  evidence_ref=excluded.evidence_ref, confirmed_at=excluded.confirmed_at,
                  expires_at=excluded.expires_at, revoked_at=excluded.revoked_at,
                  updated_at=excluded.updated_at
            """, (country, scope, status, evidence_ref.strip(), confirmed.isoformat(),
                  expiry.isoformat() if expiry else None, revoked_at, current.isoformat()))
            db.execute("""
                INSERT INTO tiktok_live_gift_country_audit
                (country_code, action, scope, status, evidence_ref, changed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (country, "approval_updated", scope, status, evidence_ref.strip(), current.isoformat()))

    def revoke(self, country_code: str, *, evidence_ref: str, now: datetime | None = None) -> None:
        self.set_approval(country_code=country_code, evidence_ref=evidence_ref,
                          confirmed_at=_now(now).isoformat(), status="revoked", now=now)

    def evaluate(self, creator_claim: dict[str, Any] | None, *, now: datetime | None = None) -> EligibilityDecision:
        if not isinstance(creator_claim, dict):
            return EligibilityDecision(False, "missing_verified_creator_claim")
        creator_id = creator_claim.get("creator_id")
        if not isinstance(creator_id, str) or not creator_id.strip():
            return EligibilityDecision(False, "missing_creator_identity")
        if creator_claim.get("verified") is not True or creator_claim.get("source") != "tiktok_verified_account":
            return EligibilityDecision(False, "untrusted_country_claim")
        try:
            country = self._country(creator_claim.get("country_code"))
        except ValueError:
            return EligibilityDecision(False, "missing_or_invalid_verified_country")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM tiktok_live_gift_country_approvals WHERE country_code=? AND scope=?",
                (country, SCOPE),
            ).fetchone()
        if row is None:
            return EligibilityDecision(False, "country_not_approved", country)
        if row["status"] != "approved" or row["revoked_at"] is not None:
            return EligibilityDecision(False, "approval_not_active", country)
        current = _now(now)
        if _utc(row["confirmed_at"]) is None or _utc(row["confirmed_at"]) > current:
            return EligibilityDecision(False, "approval_not_yet_effective", country)
        expiry = _utc(row["expires_at"])
        if expiry is not None and current >= expiry:
            return EligibilityDecision(False, "approval_expired", country)
        return EligibilityDecision(True, "approved", country)

    def audit_log(self, country_code: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if country_code is None:
                rows = db.execute("SELECT * FROM tiktok_live_gift_country_audit ORDER BY audit_id").fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM tiktok_live_gift_country_audit WHERE country_code=? ORDER BY audit_id",
                    (self._country(country_code),),
                ).fetchall()
        return [dict(row) for row in rows]
