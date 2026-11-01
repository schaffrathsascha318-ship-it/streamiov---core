"""SQLite-backed, evidence-first rights register. This is not legal advice."""
from __future__ import annotations
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

RIGHTS_STATUSES = frozenset({"CLEARED", "PUBLIC_DOMAIN_VERIFIED", "LICENSE_REQUIRED", "RIGHTS_UNCLEAR", "BLOCKED"})
RELEASE_ACTIVITIES = frozenset({"preservation", "distribution", "port", "remaster", "remake", "modernization_2d_to_3d", "sequel", "marketing", "title_or_brand_use"})

class RightsError(ValueError):
    pass

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _date(value, field):
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        raise RightsError(f"{field} must be YYYY-MM-DD.") from None

def _https(value):
    parsed = urlparse(value if isinstance(value, str) else "")
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RightsError("Evidence sources must be HTTPS URLs without embedded credentials.")

class RightsRegister:
    """Store per-component, per-activity evidence and fail closed on release."""

    def __init__(self, database):
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS titles(title_id TEXT PRIMARY KEY,title TEXT NOT NULL,territory TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS components(component_id TEXT PRIMARY KEY,title_id TEXT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,component_type TEXT NOT NULL,description TEXT NOT NULL,rights_holder TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,component_id TEXT NOT NULL REFERENCES components(component_id) ON DELETE CASCADE,source_url TEXT NOT NULL,source_authority TEXT NOT NULL,accessed_at TEXT NOT NULL,relevant_excerpt TEXT NOT NULL,notes TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assessments(assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,component_id TEXT NOT NULL REFERENCES components(component_id) ON DELETE CASCADE,activity TEXT NOT NULL,status TEXT NOT NULL,legal_basis TEXT NOT NULL,restrictions TEXT NOT NULL,reviewer TEXT NOT NULL,human_review_required INTEGER NOT NULL,checked_at TEXT NOT NULL,next_review_at TEXT,UNIQUE(component_id,activity));
            """)

    def _db(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def create_title(self, title_id, title, territory):
        if not all(isinstance(x, str) and x.strip() for x in (title_id, title, territory)):
            raise RightsError("title_id, title, and territory are required.")
        with self._db() as db:
            db.execute("INSERT INTO titles VALUES(?,?,?,?)", (title_id, title.strip(), territory.strip(), _now()))

    def add_component(self, component_id, title_id, component_type, description, rights_holder=""):
        if not all(isinstance(x, str) and x.strip() for x in (component_id, title_id, component_type, description)):
            raise RightsError("Component id, title id, type, and description are required.")
        with self._db() as db:
            if not db.execute("SELECT 1 FROM titles WHERE title_id=?", (title_id,)).fetchone():
                raise RightsError("Unknown title_id.")
            db.execute("INSERT INTO components VALUES(?,?,?,?,?,?)", (component_id, title_id, component_type, description, rights_holder.strip(), _now()))

    def add_evidence(self, component_id, source_url, source_authority, accessed_at, relevant_excerpt, notes=""):
        _https(source_url)
        _date(accessed_at, "accessed_at")
        if not all(isinstance(x, str) and x.strip() for x in (component_id, source_authority, relevant_excerpt)):
            raise RightsError("Evidence needs a component, authority, and excerpt.")
        with self._db() as db:
            if not db.execute("SELECT 1 FROM components WHERE component_id=?", (component_id,)).fetchone():
                raise RightsError("Unknown component_id.")
            cur = db.execute("INSERT INTO evidence(component_id,source_url,source_authority,accessed_at,relevant_excerpt,notes) VALUES(?,?,?,?,?,?)", (component_id, source_url, source_authority.strip(), accessed_at, relevant_excerpt.strip(), notes.strip()))
            return int(cur.lastrowid)

    def assess(self, component_id, activity, status, legal_basis, reviewer, restrictions="", human_review_required=True, next_review_at=None):
        if activity not in RELEASE_ACTIVITIES:
            raise RightsError("Unsupported rights activity.")
        if status not in RIGHTS_STATUSES:
            raise RightsError("Unsupported rights status.")
        if not all(isinstance(x, str) and x.strip() for x in (component_id, legal_basis, reviewer)):
            raise RightsError("Assessment requires component, legal basis, and reviewer.")
        if next_review_at:
            _date(next_review_at, "next_review_at")
        with self._db() as db:
            if not db.execute("SELECT 1 FROM components WHERE component_id=?", (component_id,)).fetchone():
                raise RightsError("Unknown component_id.")
            count = db.execute("SELECT COUNT(*) FROM evidence WHERE component_id=?", (component_id,)).fetchone()[0]
            if status in {"CLEARED", "PUBLIC_DOMAIN_VERIFIED"} and count == 0:
                raise RightsError("Positive clearance requires recorded evidence.")
            db.execute("""INSERT INTO assessments(component_id,activity,status,legal_basis,restrictions,reviewer,human_review_required,checked_at,next_review_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(component_id,activity) DO UPDATE SET status=excluded.status,legal_basis=excluded.legal_basis,restrictions=excluded.restrictions,reviewer=excluded.reviewer,human_review_required=excluded.human_review_required,checked_at=excluded.checked_at,next_review_at=excluded.next_review_at""",
            (component_id, activity, status, legal_basis.strip(), restrictions.strip(), reviewer.strip(), int(bool(human_review_required)), _now(), next_review_at))

    def release_decision(self, title_id, activity):
        if activity not in RELEASE_ACTIVITIES:
            raise RightsError("Unsupported rights activity.")
        with self._db() as db:
            title = db.execute("SELECT * FROM titles WHERE title_id=?", (title_id,)).fetchone()
            if not title:
                raise RightsError("Unknown title_id.")
            components = db.execute("SELECT * FROM components WHERE title_id=? ORDER BY component_id", (title_id,)).fetchall()
            blockers = []
            if not components:
                blockers.append({"reason": "no_components_registered"})
            for component in components:
                aid = component["component_id"]
                assessment = db.execute("SELECT * FROM assessments WHERE component_id=? AND activity=?", (aid, activity)).fetchone()
                evidence_count = db.execute("SELECT COUNT(*) FROM evidence WHERE component_id=?", (aid,)).fetchone()[0]
                if not assessment:
                    blockers.append({"component_id": aid, "reason": "assessment_missing"})
                    continue
                if assessment["status"] not in {"CLEARED", "PUBLIC_DOMAIN_VERIFIED"}:
                    blockers.append({"component_id": aid, "reason": assessment["status"]})
                if evidence_count == 0:
                    blockers.append({"component_id": aid, "reason": "evidence_missing"})
                if assessment["human_review_required"]:
                    blockers.append({"component_id": aid, "reason": "human_review_required"})
                if assessment["next_review_at"] and date.fromisoformat(assessment["next_review_at"]) < date.today():
                    blockers.append({"component_id": aid, "reason": "assessment_stale"})
            return {"title_id": title_id, "title": title["title"], "territory": title["territory"], "activity": activity,
                    "decision": "BLOCKED" if blockers else "ELIGIBLE_FOR_RELEASE_REVIEW", "blockers": blockers,
                    "checked_at": _now(), "legal_notice": "Workflow gate only; not a legal opinion."}

    def dossier(self, title_id):
        with self._db() as db:
            title = db.execute("SELECT * FROM titles WHERE title_id=?", (title_id,)).fetchone()
            if not title:
                raise RightsError("Unknown title_id.")
            result = dict(title)
            result["components"] = []
            for component in db.execute("SELECT * FROM components WHERE title_id=? ORDER BY component_id", (title_id,)):
                item = dict(component)
                item["evidence"] = [dict(x) for x in db.execute("SELECT * FROM evidence WHERE component_id=? ORDER BY evidence_id", (item["component_id"],))]
                item["assessments"] = [dict(x) for x in db.execute("SELECT * FROM assessments WHERE component_id=? ORDER BY activity", (item["component_id"],))]
                result["components"].append(item)
            return result
