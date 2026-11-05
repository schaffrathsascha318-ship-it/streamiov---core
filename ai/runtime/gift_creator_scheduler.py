"""Persistent schedule for the proactive Streamiov Gift Creator.

This module only schedules bounded specialist jobs. It does not claim to run a
daemon, generate binary 3D assets, publish gifts, or activate TikTok gifts.
A supervised process must call schedule_due() and run the existing
SpecialistWorker against the same durable queue database.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from ai.core.orchestrator import SpecialistTask
from ai.runtime.task_queue import SpecialistTaskQueue


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "gift_creator_agent.json"
SEASON_DATES = {
    "winter_christmas": (12, 25),
    "new_year": (1, 1),
    "spring": (3, 20),
    "summer": (6, 21),
    "autumn_halloween": (10, 31),
}


class GiftCreatorScheduleError(RuntimeError):
    pass


class GiftCreatorScheduler:
    """Idempotently enqueue weekly original concepts and seasonal preparation."""

    def __init__(
        self,
        queue: SpecialistTaskQueue,
        database_path: str | Path,
        *,
        config_path: str | Path = DEFAULT_CONFIG,
    ) -> None:
        self.queue = queue
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            path = Path(self.database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                raise GiftCreatorScheduleError("Scheduler database must not be a symlink.")
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._initialize()

    def _load_config(self) -> dict:
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GiftCreatorScheduleError("Gift Creator configuration is unavailable or invalid.") from exc
        cadence = config.get("cadence", {})
        if config.get("agent_id") != "streamiov-gift-creator":
            raise GiftCreatorScheduleError("Unexpected Gift Creator agent identity.")
        if cadence.get("never_auto_publish") is not True:
            raise GiftCreatorScheduleError("Gift Creator must never auto-publish.")
        batch_size = cadence.get("concept_batch_size")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 12:
            raise GiftCreatorScheduleError("Concept batch size must be between 1 and 12.")
        return config

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS gift_creator_schedule (
                    event_key TEXT PRIMARY KEY,
                    task_ids TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL
                )"""
            )

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise GiftCreatorScheduleError("Schedule timestamps must be timezone-aware.")
        return current.astimezone(timezone.utc)

    @staticmethod
    def _next_occurrence(today: date, month: int, day: int) -> date:
        candidate = date(today.year, month, day)
        if candidate < today:
            candidate = date(today.year + 1, month, day)
        return candidate

    def _seasonal_events(self, today: date) -> list[tuple[str, str, int]]:
        lead = self.config["cadence"].get("seasonal_preview_lead_days", 60)
        events = []
        for collection in self.config.get("collections", []):
            collection_id = collection.get("id")
            if collection_id not in SEASON_DATES:
                continue
            month, day = SEASON_DATES[collection_id]
            occurrence = self._next_occurrence(today, month, day)
            days_until = (occurrence - today).days
            if 0 <= days_until <= lead:
                events.append((collection_id, collection.get("name", collection_id), days_until))
        return events

    def _enqueue_once(self, event_key: str, tasks: list[SpecialistTask], now: datetime) -> bool:
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM gift_creator_schedule WHERE event_key=?", (event_key,)
            ).fetchone():
                return False

        # Deterministic IDs make recovery safe if the process stops after queue
        # insertion but before the schedule marker is committed.
        existing = [self.queue.get(task.task_id) for task in tasks]
        if not all(existing):
            missing = [task for task, row in zip(tasks, existing) if row is None]
            if len(missing) != len(tasks):
                raise GiftCreatorScheduleError("Partial scheduled task plan found; refusing duplicate enqueue.")
            self.queue.enqueue_plan(tasks, max_attempts=2)

        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO gift_creator_schedule(event_key,task_ids,scheduled_at) VALUES(?,?,?)",
                (event_key, json.dumps([task.task_id for task in tasks]), now.isoformat()),
            )
        return True

    def schedule_due(self, now: datetime | None = None) -> dict:
        current = self._now(now)
        today = current.date()
        year, week, _ = today.isocalendar()
        weekly_key = f"weekly:{year}-W{week:02d}"
        batch_size = self.config["cadence"]["concept_batch_size"]
        weekly_tasks = []
        for index in range(batch_size):
            task_id = f"gift-week-{year}w{week:02d}-{index + 1}"
            prompt = (
                "Entwickle genau EIN neues, eigenständiges Streamiov-Geschenkkonzept als "
                "prüfbares Produktionsbriefing. Lies zuerst data/game_actions/streamiov_original_gift_family.json, "
                "data/game_actions/gift_catalog.json und die vorhandenen Dateien unter dist/streamiov-homepage-worker/public/assets/gifts. "
                "Die Rose ist unveränderlich. Keine TikTok-Geschenke kopieren, keine generischen Motive umbenennen. "
                "Vergleiche Silhouette, Mechanik, Material und Animation gegen den Bestand. "
                "Liefere Name, eindeutige Silhouette, Story, Materialien, Rig, individuelle Intro/Haupt/Outro-Animation, "
                "Soundidee, kleine Galerieansicht, technische Risiken und begründete Originalität. "
                "Kennzeichne das Ergebnis als Entwurf; keine Katalogaktivierung, Veröffentlichung oder TikTok-Einreichung. "
                f"Dies ist Konzept {index + 1} von {batch_size} im Zyklus {year}-W{week:02d}. "
                "Wenn der Bestand nicht gelesen werden kann, stoppe statt Ähnlichkeit zu behaupten."
            )
            weekly_tasks.append(SpecialistTask(task_id, "gifts", prompt))

        scheduled = []
        if self._enqueue_once(weekly_key, weekly_tasks, current):
            scheduled.append(weekly_key)

        seasonal = []
        for collection_id, name, days_until in self._seasonal_events(today):
            event_key = f"season:{collection_id}:{today.year if collection_id != 'new_year' else (today.year if today.month == 1 else today.year + 1)}"
            task_id = "gift-season-" + hashlib.sha256(event_key.encode()).hexdigest()[:16]
            prompt = (
                f"Erstelle die saisonale Streamiov-Originalkollektion '{name}'. Das Ereignis liegt in {days_until} Tagen. "
                "Prüfe zuerst den gesamten Geschenkbestand und die Originalitätsregeln. "
                "Plane eine eigenständige Kollektion mit mehreren unterscheidbaren Geschenken, 3D-Modellbriefings, "
                "individuellen Animationen, Vorschauen und QA-Kriterien. Keine bekannten TikTok-Geschenke nachbilden. "
                "Rose unverändert lassen. Ergebnisse bleiben Entwürfe und dürfen nicht automatisch veröffentlicht, "
                "aktiviert oder an TikTok übermittelt werden."
            )
            if self._enqueue_once(event_key, [SpecialistTask(task_id, "gifts", prompt)], current):
                scheduled.append(event_key)
            seasonal.append({"collection": collection_id, "days_until": days_until})

        return {"scheduled": scheduled, "seasonal_windows": seasonal, "weekly_batch_size": batch_size}
