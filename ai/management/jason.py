"""Jason: read-only project administration and portfolio visibility.

Jason tracks project areas, persistent Chief missions, specialist assignments,
and blockers. Technical planning and implementation remain owned by the AI
Chief; Jason does not impersonate a specialist or alter production state.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from ai.specialists import SPECIALISTS


PROJECT_AREAS = (
    "ai", "core", "modules", "services", "host", "dist",
    "games", "data", "infrastructure", "tests", "docs",
)


class JasonAdministrationError(RuntimeError):
    """Raised when project administration cannot safely inspect its inputs."""


def _read_only_connection(path: Path):
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return None
    if path.is_symlink():
        raise JasonAdministrationError(f"Refusing symlink database: {path}")
    uri = f"file:{quote(str(resolved))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


class JasonProjectAdministrator:
    """Build a grounded project overview without changing project or DB state."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        mission_db: str | Path = ".streamiov/ai-missions.sqlite3",
        queue_db: str | Path = ".streamiov/specialist-queue.sqlite3",
    ) -> None:
        self.root = Path(project_root).expanduser().resolve()
        if not self.root.is_dir():
            raise JasonAdministrationError("Project root must be an existing directory.")
        self.mission_db = Path(mission_db)
        self.queue_db = Path(queue_db)

    def _mission_overview(self) -> dict:
        result = {"database": str(self.mission_db), "available": False, "missions": []}
        connection = _read_only_connection(self.mission_db)
        if connection is None:
            return result
        try:
            if not _table_exists(connection, "development_missions"):
                return result
            result["available"] = True
            rows = connection.execute(
                """SELECT mission_id, goal, status, cycle, summary, created_at, updated_at
                   FROM development_missions ORDER BY updated_at DESC, mission_id"""
            ).fetchall()
            for row in rows:
                counts = {"queued": 0, "running": 0, "succeeded": 0}
                if _table_exists(connection, "development_mission_tasks"):
                    task_rows = connection.execute(
                        """SELECT status, COUNT(*) AS amount
                           FROM development_mission_tasks WHERE mission_id=? GROUP BY status""",
                        (row["mission_id"],),
                    ).fetchall()
                    counts.update({item["status"]: item["amount"] for item in task_rows})
                result["missions"].append({
                    "mission_id": row["mission_id"],
                    "goal": row["goal"],
                    "status": row["status"],
                    "cycle": row["cycle"],
                    "summary": row["summary"],
                    "updated_at": row["updated_at"],
                    "tasks": counts,
                })
            return result
        finally:
            connection.close()

    def _queue_overview(self) -> dict:
        result = {"database": str(self.queue_db), "available": False, "assignments": []}
        connection = _read_only_connection(self.queue_db)
        if connection is None:
            return result
        try:
            if not _table_exists(connection, "specialist_tasks"):
                return result
            result["available"] = True
            rows = connection.execute(
                """SELECT specialist, status, COUNT(*) AS amount
                   FROM specialist_tasks GROUP BY specialist, status
                   ORDER BY specialist, status"""
            ).fetchall()
            result["assignments"] = [
                {"specialist": row["specialist"], "status": row["status"], "count": row["amount"]}
                for row in rows
            ]
            return result
        finally:
            connection.close()

    def snapshot(self) -> dict:
        areas = [
            {"name": name, "present": (self.root / name).is_dir()}
            for name in PROJECT_AREAS
        ]
        missions = self._mission_overview()
        queue = self._queue_overview()
        specialists = [
            {"key": key, "title": definition.title, "mission": definition.mission}
            for key, definition in SPECIALISTS.items()
        ]
        blockers = []
        if not missions["available"]:
            blockers.append("No persistent Chief mission database found; mission progress is not yet observable.")
        if not queue["available"]:
            blockers.append("No specialist task queue database found; queued assignments are not yet observable.")
        active_missions = [item for item in missions["missions"] if item["status"] == "active"]
        failed_queue = [item for item in queue["assignments"] if item["status"] == "failed"]
        if failed_queue:
            blockers.append("One or more specialist queue assignments are marked failed.")
        return {
            "administrator": "Jason",
            "role": "Project administration, portfolio overview, assignment and dependency tracking",
            "technical_owner": "AI Chief",
            "specialist_count": len(specialists),
            "specialists": specialists,
            "project_root": str(self.root),
            "project_areas": areas,
            "missions": missions,
            "specialist_queue": queue,
            "active_mission_count": len(active_missions),
            "blockers": blockers,
            "authority": {
                "may_track_and_report": True,
                "may_assign_and_coordinate": True,
                "may_override_chief_technical_decisions": False,
                "may_deploy_or_change_production": False,
                "may_access_secrets_or_credentials": False,
            },
        }

    def render_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=False, indent=2)
