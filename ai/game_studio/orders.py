"""Intake and governance for externally commissioned StreamioV game projects."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from ai.game_studio.builder import (
    REQUIRED_TEXT, SAFE_ID, GameBriefError,
    create_design_workspace, validate_game_brief,
)


QUESTIONS = {
    "title": "Wie heißt das Spiel?",
    "genre": "Welches Genre soll das Spiel haben?",
    "vision": "Beschreibe die Grundidee und das Ziel des Spiels.",
    "core_gameplay": "Welche Haupttätigkeit hat der Spieler?",
    "progression": "Wie funktioniert Fortschritt und Belohnung?",
    "art_direction": "Welchen Grafikstil soll das Spiel haben?",
    "audio_direction": "Welche Musik und Soundeffekte sind geplant?",
    "accessibility": "Welche Barrierefreiheit ist vorgesehen?",
    "test_plan": "Wie soll das Spiel geprüft werden?",
    "target_platforms": "Auf welchen Plattformen soll das Spiel laufen?",
    "signature_mechanics": "Nenne mindestens zwei besondere Spielmechaniken.",
    "core_loop": "Beschreibe mindestens drei Schritte der Hauptschleife.",
    "level_plan": "Beschreibe mindestens drei Level oder Herausforderungen.",
    "controls": "Welche Eingaben werden auf welchen Geräten unterstützt?",
    "rights": "Wer besitzt Idee, Grafik, Code und Audio? Welche Lizenzen liegen vor?",
    "client": "Wer ist Auftraggeber und mit welcher Referenz?",
    "purpose": "Welchen Zweck erfüllt das Spiel?",
    "target_audience": "Wer ist die Zielgruppe?",
    "scope": "Welchen Umfang soll die erste Version haben?",
    "materials": "Welche Materialien und Referenzen darf das Team verwenden?",
}
MISSION_TEMPLATE = (
    ("game-design", "Game Design"),
    ("programming", "Programmierung"),
    ("graphics", "Grafik"),
    ("animation", "Animation"),
    ("sound", "Sound"),
    ("level-design", "Leveldesign"),
    ("gameplay", "Gameplay"),
    ("ui-ux", "UI/UX"),
    ("backend", "Backend"),
    ("multiplayer", "Multiplayer"),
    ("quality-assurance", "Qualitätssicherung"),
    ("performance", "Performance"),
    ("build", "Build-Erstellung"),
)
MISSION_STATES = ("pending", "in_progress", "verified", "blocked")


class OrderIntakeError(ValueError):
    """Safe-to-return validation or workspace error for a game order."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _slug(value: str) -> str:
    letters = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return letters[:60].strip("-") or "streamiov-game"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _read_json(path: Path, default: dict | None = None) -> dict:
    if not path.is_file() or path.is_symlink():
        return dict(default or {})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return dict(default or {})
    return value if isinstance(value, dict) else dict(default or {})


def missing_requirements(order: Any) -> list[dict[str, str]]:
    """Return concrete follow-up questions for an incomplete external order."""
    if not isinstance(order, dict):
        raise OrderIntakeError("Auftrag muss ein JSON-Objekt sein.")
    missing: list[dict[str, str]] = []
    for field in ("title", "genre", *REQUIRED_TEXT):
        if not _text(order.get(field)):
            missing.append({"field": field, "question": QUESTIONS[field]})
    for field, minimum in (("target_platforms", 1), ("signature_mechanics", 2),
                           ("core_loop", 3), ("level_plan", 3), ("materials", 1)):
        value = order.get(field)
        if not isinstance(value, list) or len(value) < minimum or any(not _text(item) for item in value):
            missing.append({"field": field, "question": QUESTIONS[field]})
    controls = order.get("controls")
    if not isinstance(controls, dict) or not controls:
        missing.append({"field": "controls", "question": QUESTIONS["controls"]})
    rights = order.get("rights")
    if not isinstance(rights, dict) or rights.get("original_concept") is not True:
        missing.append({"field": "rights", "question": QUESTIONS["rights"]})
    elif not isinstance(rights.get("third_party_components", []), list):
        missing.append({"field": "rights", "question": QUESTIONS["rights"]})
    client = order.get("client")
    if not isinstance(client, dict) or not _text(client.get("name")) or not _text(client.get("reference")):
        missing.append({"field": "client", "question": QUESTIONS["client"]})
    for field in ("purpose", "target_audience", "scope"):
        if not _text(order.get(field)):
            missing.append({"field": field, "question": QUESTIONS[field]})
    return missing


def create_order(order: Any, repository_root: str | Path) -> dict[str, Any]:
    """Create an isolated design workspace only after a complete, lawful brief."""
    if isinstance(order, dict):
        rights = order.get("rights")
        if isinstance(rights, dict) and rights.get("original_concept") is False:
            return {"status": "REJECTED",
                    "reason": "Only explicitly original concepts enter this clean-room builder.",
                    "workspace": None}
    missing = missing_requirements(order)
    if missing:
        return {"status": "NEEDS_INPUT", "missing": missing, "workspace": None}
    brief = dict(order)
    brief.setdefault("id", _slug(order["title"]))
    try:
        audit = validate_game_brief(brief)
    except GameBriefError as exc:
        return {"status": "REJECTED", "reason": str(exc), "workspace": None}
    root = Path(repository_root).resolve()
    workspace = create_design_workspace(brief, root)
    target = (root / workspace["workspace"]).resolve()
    order_file = target / "order.json"
    if order_file.exists():
        raise OrderIntakeError("Auftragsdatei existiert bereits.")
    missions = [{"id": mission_id, "title": title, "status": "pending",
                 "assignee": "", "evidence_ref": "", "updated_at": ""}
                for mission_id, title in MISSION_TEMPLATE]
    _write_json(target / "order.json", {
        "order_id": audit["project_id"],
        "status": "DESIGN_WORKSPACE",
        "created_at": _utc_now(),
        "client": {
            "name": _text(order["client"].get("name"))[:120],
            "reference": _text(order["client"].get("reference"))[:120],
            "confidential": bool(order["client"].get("confidential", True)),
        },
        "purpose": _text(order["purpose"])[:400],
        "target_audience": _text(order["target_audience"])[:400],
        "scope": _text(order["scope"])[:400],
        "materials": [item for item in order["materials"] if _text(item)][:30],
        "rights": brief["rights"],
        "publication_approved": False,
        "published": False,
    })
    _write_json(target / "missions.json", {
        "order_id": audit["project_id"], "missions": missions,
    })
    _write_json(target / "progress.json", {
        "order_id": audit["project_id"],
        "events": [{"at": _utc_now(), "actor": "intake", "event": "workspace_created",
                    "mission_id": "", "status": "DESIGN_BRIEF_VALIDATED", "evidence_ref": ""}],
    })
    _write_json(target / "access.json", {
        "order_id": audit["project_id"],
        "workspace_isolation": "games/ai_created/<order_id>",
        "allowed_roles": ["ai-chief", "game-builder", "independent-reviewer", "owner"],
        "client_data_access": "owner-and-assigned-team-only",
        "external_actions_allowed": False,
    })
    return {
        "status": "WORKSPACE_CREATED",
        "order_id": audit["project_id"],
        "workspace": workspace["workspace"],
        "missing": [],
        "release_ready": False,
        "publication_approved": False,
    }


def _workspace(repository_root: str | Path, order_id: Any) -> Path:
    if not isinstance(order_id, str) or not SAFE_ID.fullmatch(order_id):
        raise OrderIntakeError("Ungültige Auftrags-ID.")
    root = Path(repository_root).resolve()
    games_root = root / "games" / "ai_created"
    if games_root.is_symlink():
        raise OrderIntakeError("Der Arbeitsbereich darf kein Symlink sein.")
    workspace_path = games_root / order_id
    if workspace_path.is_symlink():
        raise OrderIntakeError("Der Auftragsarbeitsbereich darf kein Symlink sein.")
    target = workspace_path.resolve()
    if target.parent != games_root.resolve() or not target.is_dir():
        raise OrderIntakeError("Auftragsarbeitsbereich nicht gefunden.")
    return target


def update_mission(repository_root: str | Path, order_id: Any, mission_id: Any,
                   status: Any, evidence_ref: Any = "", actor: Any = "ai-chief") -> dict[str, Any]:
    target = _workspace(repository_root, order_id)
    path = target / "missions.json"
    data = _read_json(path)
    missions = data.get("missions")
    if not isinstance(missions, list):
        raise OrderIntakeError("Missionsliste fehlt.")
    entry = next((item for item in missions if isinstance(item, dict) and item.get("id") == mission_id), None)
    if entry is None:
        raise OrderIntakeError("Mission nicht gefunden.")
    if status not in MISSION_STATES:
        raise OrderIntakeError("Ungültiger Missionsstatus.")
    reference = " ".join(str(evidence_ref or "").split())[:200]
    if status == "verified" and not reference:
        raise OrderIntakeError("Verifizierte Mission benötigt einen Nachweis.")
    current = entry.get("status")
    if status == "verified" and current == "blocked":
        raise OrderIntakeError("Blockierte Mission muss zuerst freigegeben werden.")
    entry.update({"status": status, "evidence_ref": reference,
                  "assignee": " ".join(str(actor or "ai-chief").split())[:80],
                  "updated_at": _utc_now()})
    _write_json(path, data)
    progress = _read_json(target / "progress.json", {"events": []})
    events = progress.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        progress["events"] = events
    events.append({"at": _utc_now(), "actor": str(actor or "ai-chief")[:80],
                   "event": "mission_status", "mission_id": mission_id,
                   "status": status, "evidence_ref": reference})
    _write_json(target / "progress.json", progress)
    return {"ok": True, "order_id": order_id, "mission_id": mission_id, "status": status}


def record_rights_review(repository_root: str | Path, order_id: Any, review: Any) -> dict[str, Any]:
    target = _workspace(repository_root, order_id)
    if not isinstance(review, dict) or review.get("status") not in {"approved", "rejected"}:
        raise OrderIntakeError("Rechteprüfung benötigt Status approved oder rejected.")
    reviewer = _text(review.get("reviewer"))
    reference = _text(review.get("review_ref"))
    inventory = review.get("asset_inventory")
    if not reviewer or not reference or not isinstance(inventory, list) or not inventory:
        raise OrderIntakeError("Rechteprüfung benötigt Prüfer, Referenz und Asset-Inventar.")
    _write_json(target / "rights-review.json", {
        "status": review["status"], "reviewer": reviewer[:120],
        "review_ref": reference[:200],
        "asset_inventory": [str(item)[:200] for item in inventory][:50],
        "reviewed_at": _utc_now(),
    })
    return {"ok": True, "order_id": order_id, "rights_status": review["status"]}


def record_release_gate(repository_root: str | Path, order_id: Any, gate: Any) -> dict[str, Any]:
    target = _workspace(repository_root, order_id)
    if not isinstance(gate, dict) or gate.get("release_ready") is not True:
        raise OrderIntakeError("Freigabe erst nach bestandenem Qualitäts-Gate möglich.")
    if gate.get("independent_review_confirmed") is not True:
        raise OrderIntakeError("Unabhängige Prüfung fehlt.")
    _write_json(target / "release-gate.json", {
        "status": gate.get("status", "RELEASE_REVIEW_READY"),
        "release_ready": True,
        "independent_review_confirmed": True,
        "missing_gates": gate.get("missing_gates", []),
        "recorded_at": _utc_now(),
    })
    return {"ok": True, "order_id": order_id, "release_gate": "passed"}


def record_client_approval(repository_root: str | Path, order_id: Any, approval: Any) -> dict[str, Any]:
    target = _workspace(repository_root, order_id)
    if not isinstance(approval, dict):
        raise OrderIntakeError("Freigabe muss ein Objekt sein.")
    approved_by = _text(approval.get("approved_by"))
    reference = _text(approval.get("reference"))
    scope = _text(approval.get("scope"))
    if not approved_by or not reference or not scope:
        raise OrderIntakeError("Freigabe benötigt Person, Referenz und Umfang.")
    _write_json(target / "client-approval.json", {
        "approved_by": approved_by[:120], "reference": reference[:200],
        "scope": scope[:400], "approved_at": _utc_now(),
    })
    return {"ok": True, "order_id": order_id, "client_approval": "recorded"}


def authorize_publication(repository_root: str | Path, order_id: Any) -> dict[str, Any]:
    target = _workspace(repository_root, order_id)
    gate = _read_json(target / "release-gate.json")
    rights = _read_json(target / "rights-review.json")
    approval = _read_json(target / "client-approval.json")
    missing = []
    if gate.get("release_ready") is not True:
        missing.append("release_gate")
    if rights.get("status") != "approved":
        missing.append("rights_approval")
    if not approval.get("approved_by"):
        missing.append("client_approval")
    if missing:
        return {"ok": False, "status": "PUBLICATION_BLOCKED", "missing": missing,
                "published": False}
    publication = {
        "ok": True, "status": "PUBLICATION_AUTHORIZED", "approved": True,
        "published": False, "approved_at": _utc_now(),
        "note": "Freigabe für Veröffentlichung; tatsächliches Veröffentlichen bleibt ein separater Schritt.",
    }
    _write_json(target / "publication.json", publication)
    order = _read_json(target / "order.json")
    order["publication_approved"] = True
    order["status"] = "PUBLICATION_AUTHORIZED"
    _write_json(target / "order.json", order)
    return publication


def bind_task_workspace(repository_root: str | Path, order_id: Any, mission_id: Any,
                        task_id: Any, worker_id: Any = "ai-chief",
                        *, cycle: int = 1, lease_seconds: int = 3600,
                        database_path: str | Path | None = None) -> dict[str, Any]:
    """Bind a specialist task workspace to an isolated external order project."""
    from ai.runtime.task_workspaces import TaskWorkspaceStore

    if (not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128
            or "/" in task_id or "\\" in task_id or ".." in task_id):
        raise OrderIntakeError("Ungültige Task-ID.")
    if not isinstance(mission_id, str) or not SAFE_ID.fullmatch(mission_id):
        raise OrderIntakeError("Ungültige Missions-ID.")
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0:
        raise OrderIntakeError("Ungültiger Zyklus.")
    target = _workspace(repository_root, order_id)
    missions_path = target / "missions.json"
    data = _read_json(missions_path)
    missions = data.get("missions")
    if not isinstance(missions, list) or not any(
            isinstance(item, dict) and item.get("id") == mission_id for item in missions):
        raise OrderIntakeError("Mission nicht gefunden.")
    root = Path(repository_root).resolve()
    database = Path(database_path).resolve() if database_path else root / ".streamiov" / "task-workspaces.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    store = TaskWorkspaceStore(database)
    workspace, created = store.ensure_workspace(
        task_id, f"game-order-{order_id}-{mission_id}", cycle, target,
        " ".join(str(worker_id or "ai-chief").split())[:80], max(60, min(int(lease_seconds), 86400)),
    )
    update_mission(root, order_id, mission_id, "in_progress",
                   evidence_ref=f"task-workspace:{task_id}", actor=worker_id)
    progress = _read_json(target / "progress.json", {"events": []})
    events = progress.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        progress["events"] = events
    events.append({"at": _utc_now(), "actor": str(worker_id or "ai-chief")[:80],
                   "event": "task_workspace_bound", "mission_id": mission_id,
                   "status": "in_progress", "evidence_ref": task_id[:200]})
    _write_json(target / "progress.json", progress)
    return {
        "ok": True, "order_id": order_id, "mission_id": mission_id, "task_id": task_id,
        "workspace_created": created,
        "workspace": workspace.relative_to(root).as_posix() if root in workspace.parents else str(workspace),
        "integration_status": "pending",
    }


def order_summary(repository_root: str | Path, order_id: Any) -> dict[str, Any]:
    target = _workspace(repository_root, order_id)
    order = _read_json(target / "order.json")
    missions = _read_json(target / "missions.json").get("missions", [])
    missions = missions if isinstance(missions, list) else []
    counts = {state: sum(1 for item in missions if isinstance(item, dict) and item.get("status") == state)
              for state in MISSION_STATES}
    rights = _read_json(target / "rights-review.json")
    approval = _read_json(target / "client-approval.json")
    publication = _read_json(target / "publication.json")
    gate = _read_json(target / "release-gate.json")
    return {
        "order_id": order_id,
        "status": order.get("status", "unknown"),
        "client": order.get("client", {}),
        "mission_counts": counts,
        "rights_status": rights.get("status", "pending"),
        "independent_release_gate": gate.get("status", "not_recorded"),
        "client_approval_recorded": bool(approval.get("approved_by")),
        "publication_approved": publication.get("approved", False),
        "published": publication.get("published", False),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="StreamioV external game order intake")
    parser.add_argument("order", help="UTF-8 JSON file containing the external game order")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--summary", metavar="ORDER_ID",
                        help="Print the honest status summary for an existing order")
    args = parser.parse_args()
    try:
        if args.summary:
            result = order_summary(args.repository_root, args.summary)
        else:
            result = create_order(json.loads(Path(args.order).read_text(encoding="utf-8")),
                                  args.repository_root)
    except (OSError, json.JSONDecodeError, OrderIntakeError) as exc:
        parser.exit(2, f"streamiov-game-orders: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
