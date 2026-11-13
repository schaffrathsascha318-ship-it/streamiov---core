"""Persistent, continuously resumable development missions.

A mission is not a single model call or a bounded queue batch. It repeatedly
plans the next useful work, executes specialist tasks, retries failed work with
backoff, and resumes from SQLite after process restarts. There is deliberately
no mission-wide task, cycle, retry, or runtime ceiling. Individual model
responses remain naturally bounded by provider limits.
"""
from __future__ import annotations

import json
import inspect
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

from ai.core.orchestrator import SpecialistTask, TaskOrchestrator, TaskPlanError
from ai.specialists.registry import get_specialist, specialist_names


class MissionEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissionPlan:
    state: Literal["continue", "completed"]
    summary: str
    tasks: tuple[SpecialistTask, ...] = ()


@dataclass(frozen=True)
class MissionSnapshot:
    mission_id: str
    goal: str
    status: str
    cycle: int
    summary: str
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    attempts: int


@dataclass(frozen=True)
class MissionTask:
    task_id: str
    mission_id: str
    cycle: int
    specialist: str
    prompt: str
    depends_on: tuple[str, ...]
    status: str
    attempts: int
    result: str
    last_error: str


class MissionPlanner(Protocol):
    def plan(self, goal: str, progress: str, *, mission_id: str, cycle: int) -> MissionPlan: ...


class AgentFactory(Protocol):
    def __call__(self, specialist: str): ...


class ContinuousDevelopmentEngine:
    """Run a durable mission until its planner verifies completion or it is stopped.

    The database is the source of truth. A stopped process can be restarted with
    the same database and mission ID; expired task/planning leases are recovered.
    """

    def __init__(
        self,
        database_path: str | Path,
        planner: MissionPlanner,
        agent_factory: AgentFactory,
        *,
        retry_base_seconds: float = 5.0,
        lease_seconds: int = 300,
    ) -> None:
        if not callable(getattr(planner, "plan", None)):
            raise TypeError("planner must provide plan()")
        if not callable(agent_factory):
            raise TypeError("agent_factory must be callable")
        if retry_base_seconds <= 0:
            raise ValueError("retry_base_seconds must be positive")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 10:
            raise ValueError("lease_seconds must be at least 10")
        self.database_path = str(database_path)
        if self.database_path == ":memory:":
            raise MissionEngineError("Continuous missions require a durable on-disk database.")
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise MissionEngineError("Mission database must not be a symlink.")
        self.planner = planner
        self.agent_factory = agent_factory
        self.retry_base_seconds = float(retry_base_seconds)
        self.lease_seconds = lease_seconds
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS development_missions (
                    mission_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','completed')),
                    cycle INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    planning_owner TEXT NOT NULL DEFAULT '',
                    planning_lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS development_mission_tasks (
                    task_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES development_missions(mission_id),
                    cycle INTEGER NOT NULL,
                    specialist TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    available_at REAL NOT NULL,
                    worker_id TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_mission_tasks_ready
                ON development_mission_tasks(mission_id,status,available_at,cycle)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_mission_tasks_lease
                ON development_mission_tasks(status,lease_until)
            """)

    def create_mission(self, goal: str, *, mission_id: str | None = None) -> str:
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 8000:
            raise MissionEngineError("Mission goal must contain 1–8000 characters.")
        mission_id = mission_id or uuid.uuid4().hex
        if not isinstance(mission_id, str) or not mission_id.strip() or len(mission_id) > 96:
            raise MissionEngineError("Mission ID must contain 1–96 characters.")
        now = time.time()
        try:
            with self._transaction() as db:
                db.execute(
                    "INSERT INTO development_missions(mission_id,goal,status,created_at,updated_at) VALUES(?,?,'active',?,?)",
                    (mission_id, goal.strip(), now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise MissionEngineError("Mission ID already exists.") from exc
        return mission_id

    def get_mission(self, mission_id: str) -> MissionSnapshot:
        with self._connection() as db:
            row = db.execute("SELECT * FROM development_missions WHERE mission_id=?", (mission_id,)).fetchone()
            if row is None:
                raise MissionEngineError("Mission not found.")
            counts = db.execute("""
                SELECT
                    SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                    SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) AS completed,
                    SUM(attempts) AS attempts
                FROM development_mission_tasks WHERE mission_id=?
            """, (mission_id,)).fetchone()
        return MissionSnapshot(
            mission_id=row["mission_id"], goal=row["goal"], status=row["status"],
            cycle=row["cycle"], summary=row["summary"],
            pending_tasks=counts["pending"] or 0, running_tasks=counts["running"] or 0,
            completed_tasks=counts["completed"] or 0, attempts=counts["attempts"] or 0,
        )

    def _progress_context(self, mission_id: str) -> str:
        with self._connection() as db:
            mission = db.execute(
                "SELECT summary FROM development_missions WHERE mission_id=?", (mission_id,)
            ).fetchone()
            rows = db.execute("""
                SELECT cycle,specialist,status,attempts,result,last_error
                FROM development_mission_tasks WHERE mission_id=?
                ORDER BY cycle DESC, updated_at DESC LIMIT 40
            """, (mission_id,)).fetchall()
        entries = []
        for row in reversed(rows):
            detail = row["result"] if row["status"] == "succeeded" else row["last_error"]
            entries.append(
                f"cycle={row['cycle']} specialist={row['specialist']} "
                f"status={row['status']} attempts={row['attempts']}: {detail[:1200]}"
            )
        return (mission["summary"] or "") + "\n\nRECENT VERIFIED TASK RECORDS:\n" + "\n".join(entries)

    def _claim_planning(self, mission_id: str, worker_id: str) -> tuple[str, int] | None:
        now = time.time()
        with self._transaction() as db:
            mission = db.execute(
                "SELECT * FROM development_missions WHERE mission_id=?", (mission_id,)
            ).fetchone()
            if mission is None:
                raise MissionEngineError("Mission not found.")
            if mission["status"] == "completed":
                return None
            active = db.execute("""
                SELECT COUNT(*) FROM development_mission_tasks
                WHERE mission_id=? AND status IN ('queued','running')
            """, (mission_id,)).fetchone()[0]
            if active:
                return None
            if mission["planning_owner"] and mission["planning_lease_until"] and mission["planning_lease_until"] > now:
                return None
            cycle = mission["cycle"] + 1
            db.execute("""
                UPDATE development_missions
                SET planning_owner=?,planning_lease_until=?,updated_at=?
                WHERE mission_id=? AND status='active'
            """, (worker_id, now + self.lease_seconds, now, mission_id))
            return mission["goal"], cycle

    def _latest_final_verification(self, mission_id: str, cycle: int) -> dict | None:
        marker = "STREAMIOV_FINAL_VERIFICATION"
        with self._connection() as db:
            row = db.execute("""
                SELECT prompt,result FROM development_mission_tasks
                WHERE mission_id=? AND cycle=? AND specialist='testing' AND status='succeeded'
                ORDER BY updated_at DESC LIMIT 1
            """, (mission_id, cycle)).fetchone()
        if row is None or marker not in row["prompt"]:
            return None
        try:
            payload = json.loads(row["result"])
        except (TypeError, json.JSONDecodeError):
            return {"verdict": "invalid", "findings": ["Verifier did not return the required JSON report."]}
        if (
            not isinstance(payload, dict)
            or set(payload) != {"verdict", "evidence", "findings"}
            or payload.get("verdict") not in {"passed", "failed"}
            or not isinstance(payload.get("evidence"), list)
            or not isinstance(payload.get("findings"), list)
        ):
            return {"verdict": "invalid", "findings": ["Verifier report did not match the required schema."]}
        if payload["verdict"] == "passed" and not payload["evidence"]:
            return {"verdict": "invalid", "findings": ["Verifier supplied no concrete evidence."]}
        return payload

    def _require_final_verification(self, mission_id: str, cycle: int, goal: str) -> MissionPlan | None:
        """Refuse planner-only completion; require a separate testing-role evidence report."""
        verification = self._latest_final_verification(mission_id, cycle - 1)
        if verification and verification["verdict"] == "passed":
            return None
        if verification and verification["verdict"] == "failed" and verification["findings"]:
            findings = json.dumps(verification["findings"], ensure_ascii=False)[:5000]
            task = SpecialistTask(
                "repair-after-final-verification",
                "repair",
                "STREAMIOV_FINAL_VERIFICATION_REPAIR: Repair the verified failures below in the existing AI Chief development work. "
                "Inspect the actual source and test output, make targeted safe changes, and run the relevant tests. "
                "Do not weaken tests or alter production/OAuth/security settings. Findings: " + findings,
            )
            summary = "Independent verification found failures; a repair task is required before completion."
        else:
            prior = ""
            if verification:
                prior = " Previous verifier findings: " + json.dumps(verification["findings"], ensure_ascii=False)[:3000]
            task = SpecialistTask(
                "mandatory-final-verification",
                "testing",
                "STREAMIOV_FINAL_VERIFICATION: Independently inspect the actual project changes for the original mission. "
                "Run the relevant automated tests and verify the requested behavior from source and test evidence. "
                "Do not edit implementation files. Return exactly one JSON object with exactly these fields: "
                '{"verdict":"passed" or "failed","evidence":["specific commands and observed results"],"findings":["specific unresolved defects"]}. '
                "Use verdict=passed only when the requested work is demonstrably correct and relevant tests pass. "
                "If anything is incomplete or tests fail, use verdict=failed and list the exact findings."
                + prior + "\nORIGINAL MISSION: " + goal,
            )
            summary = "A separate testing specialist must verify the mission before it can be marked complete."
        return MissionPlan("continue", summary, (task,))

    def _store_plan(self, mission_id: str, worker_id: str, cycle: int, plan: MissionPlan) -> None:
        if not isinstance(plan, MissionPlan) or plan.state not in {"continue", "completed"}:
            raise MissionEngineError("Planner returned an invalid mission plan.")
        if not isinstance(plan.summary, str) or not plan.summary.strip():
            raise MissionEngineError("Every mission plan needs a progress summary.")
        tasks = tuple(plan.tasks)
        if plan.state == "completed":
            with self._connection() as db:
                mission_row = db.execute(
                    "SELECT goal FROM development_missions WHERE mission_id=?", (mission_id,)
                ).fetchone()
            if mission_row is None:
                raise MissionEngineError("Mission not found during completion verification.")
            required = self._require_final_verification(mission_id, cycle, mission_row["goal"])
            if required is not None:
                plan = required
                tasks = tuple(plan.tasks)
        if plan.state == "completed" and tasks:
            raise MissionEngineError("A completed mission plan cannot contain more tasks.")
        if plan.state == "continue" and not tasks:
            raise MissionEngineError("A continuing mission plan must contain actionable tasks.")
        if tasks:
            try:
                ordered = TaskOrchestrator(lambda _role: None, max_tasks=len(tasks))._validate_and_order(tasks)
            except (TaskPlanError, ValueError) as exc:
                raise MissionEngineError(f"Planner returned an invalid task graph: {exc}") from exc
        else:
            ordered = []
        now = time.time()
        with self._transaction() as db:
            mission = db.execute(
                "SELECT planning_owner,status FROM development_missions WHERE mission_id=?",
                (mission_id,),
            ).fetchone()
            if mission is None or mission["planning_owner"] != worker_id or mission["status"] != "active":
                raise MissionEngineError("Planning lease was lost before the plan could be saved.")
            if plan.state == "completed":
                db.execute("""
                    UPDATE development_missions
                    SET status='completed',summary=?,planning_owner='',planning_lease_until=NULL,updated_at=?
                    WHERE mission_id=?
                """, (plan.summary, now, mission_id))
                return
            for task in ordered:
                get_specialist(task.specialist)
                if not task.task_id or len(task.task_id) > 96 or not task.prompt.strip():
                    raise MissionEngineError("Planned tasks need valid IDs and non-empty prompts.")
                db.execute("""
                    INSERT INTO development_mission_tasks
                    (task_id,mission_id,cycle,specialist,prompt,depends_on,status,available_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,'queued',?,?,?)
                """, (
                    f"{mission_id}:{cycle}:{task.task_id}", mission_id, cycle,
                    task.specialist, task.prompt, json.dumps(task.depends_on),
                    now, now, now,
                ))
            db.execute("""
                UPDATE development_missions
                SET cycle=?,summary=?,planning_owner='',planning_lease_until=NULL,updated_at=?
                WHERE mission_id=?
            """, (cycle, plan.summary, now, mission_id))

    def _claim_task(self, mission_id: str, worker_id: str) -> MissionTask | None:
        now = time.time()
        with self._transaction() as db:
            # An interrupted worker's lease is recoverable; attempts are never discarded.
            db.execute("""
                UPDATE development_mission_tasks
                SET status='queued',worker_id='',lease_until=NULL,
                    last_error=CASE WHEN last_error='' THEN 'Previous worker lease expired; resuming.' ELSE last_error END,
                    available_at=?,updated_at=?
                WHERE mission_id=? AND status='running' AND lease_until<=?
            """, (now, now, mission_id, now))
            rows = db.execute("""
                SELECT * FROM development_mission_tasks
                WHERE mission_id=? AND status='queued' AND available_at<=?
                ORDER BY cycle,created_at,task_id
            """, (mission_id, now)).fetchall()
            for row in rows:
                dependencies = json.loads(row["depends_on"])
                if dependencies:
                    states = {
                        item["task_id"].split(":")[-1]: item["status"]
                        for item in db.execute("""
                            SELECT task_id,status FROM development_mission_tasks
                            WHERE mission_id=? AND cycle=?
                        """, (mission_id, row["cycle"])).fetchall()
                    }
                    if any(states.get(dep) != "succeeded" for dep in dependencies):
                        continue
                db.execute("""
                    UPDATE development_mission_tasks
                    SET status='running',attempts=attempts+1,worker_id=?,lease_until=?,updated_at=?
                    WHERE task_id=? AND status='queued'
                """, (worker_id, now + self.lease_seconds, now, row["task_id"]))
                claimed = db.execute(
                    "SELECT * FROM development_mission_tasks WHERE task_id=?", (row["task_id"],)
                ).fetchone()
                return MissionTask(
                    task_id=claimed["task_id"], mission_id=claimed["mission_id"],
                    cycle=claimed["cycle"], specialist=claimed["specialist"],
                    prompt=claimed["prompt"], depends_on=tuple(json.loads(claimed["depends_on"])),
                    status=claimed["status"], attempts=claimed["attempts"],
                    result=claimed["result"], last_error=claimed["last_error"],
                )
        return None

    def _heartbeat(self, task_id: str, worker_id: str) -> None:
        now = time.time()
        with self._transaction() as db:
            cursor = db.execute("""
                UPDATE development_mission_tasks SET lease_until=?,updated_at=?
                WHERE task_id=? AND worker_id=? AND status='running' AND lease_until>?
            """, (now + self.lease_seconds, now, task_id, worker_id, now))
            if cursor.rowcount != 1:
                raise MissionEngineError("Task lease was lost.")

    def _finish_task(self, task_id: str, worker_id: str, *, result: str = "", error: str = "") -> None:
        now = time.time()
        with self._transaction() as db:
            row = db.execute("""
                SELECT attempts FROM development_mission_tasks
                WHERE task_id=? AND worker_id=? AND status='running' AND lease_until>?
            """, (task_id, worker_id, now)).fetchone()
            if row is None:
                raise MissionEngineError("Task lease expired before its result could be saved.")
            if error:
                # Retry indefinitely with exponential backoff; the attempt count is informational,
                # not a stop condition. The latest failure is fed into the next attempt.
                delay = min(self.retry_base_seconds * (2 ** min(row["attempts"] - 1, 10)), 3600.0)
                db.execute("""
                    UPDATE development_mission_tasks
                    SET status='queued',last_error=?,worker_id='',lease_until=NULL,
                        available_at=?,updated_at=? WHERE task_id=?
                """, (error[:4000], now + delay, now, task_id))
            else:
                db.execute("""
                    UPDATE development_mission_tasks
                    SET status='succeeded',result=?,last_error='',worker_id='',lease_until=NULL,
                        updated_at=? WHERE task_id=?
                """, (result[:12000], now, task_id))

    def _execute_task(self, task: MissionTask, worker_id: str, emit: Callable[[str], None]) -> None:
        stop = threading.Event()
        heartbeat_errors: list[str] = []
        interval = max(1.0, self.lease_seconds / 3)

        def heartbeat_loop() -> None:
            while not stop.wait(interval):
                try:
                    self._heartbeat(task.task_id, worker_id)
                except Exception as exc:
                    heartbeat_errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")
                    return

        thread = threading.Thread(target=heartbeat_loop, name="streamiov-mission-lease", daemon=True)
        thread.start()
        prompt = task.prompt
        if task.last_error:
            prompt += "\n\nPREVIOUS ATTEMPT FAILURE (untrusted diagnostic context):\n" + task.last_error
            prompt += "\nAddress the failure safely; inspect actual project state before changing files."
        try:
            agent = self.agent_factory(task.specialist)\n            run_parameters = inspect.signature(agent.run).parameters\n            if "checkpoint_id" in run_parameters:\n                result = agent.run(prompt, checkpoint_id=task.task_id)\n            else:\n                result = agent.run(prompt)
            if not isinstance(result, str):
                raise TypeError("Specialist agent returned a non-text result.")
            if heartbeat_errors:
                raise MissionEngineError(heartbeat_errors[-1])
            self._finish_task(task.task_id, worker_id, result=result)
            emit(json.dumps({
                "event": "task_succeeded", "task_id": task.task_id,
                "specialist": task.specialist, "attempt": task.attempts,
                "result": result[:2000],
            }, ensure_ascii=False))
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:3500]}"
            try:
                self._finish_task(task.task_id, worker_id, error=error)
            except Exception as save_error:
                error += f"; result persistence failed: {type(save_error).__name__}: {save_error}"
            emit(json.dumps({
                "event": "task_retry_scheduled", "task_id": task.task_id,
                "specialist": task.specialist, "attempt": task.attempts,
                "error": error,
            }, ensure_ascii=False))
        finally:
            stop.set()
            thread.join(timeout=interval + 1)

    def run(
        self,
        mission_id: str,
        stop_event: threading.Event,
        *,
        poll_seconds: float = 5.0,
        emit: Callable[[str], None] = print,
        worker_id: str | None = None,
    ) -> MissionSnapshot:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        worker_id = worker_id or f"chief-{uuid.uuid4().hex}"
        while not stop_event.is_set():
            snapshot = self.get_mission(mission_id)
            if snapshot.status == "completed":
                emit(json.dumps({"event": "mission_completed", "mission_id": mission_id, "summary": snapshot.summary}, ensure_ascii=False))
                return snapshot

            task = self._claim_task(mission_id, worker_id)
            if task is not None:
                self._execute_task(task, worker_id, emit)
                continue

            snapshot = self.get_mission(mission_id)
            if snapshot.pending_tasks or snapshot.running_tasks:
                stop_event.wait(poll_seconds)
                continue

            claim = self._claim_planning(mission_id, worker_id)
            if claim is None:
                stop_event.wait(poll_seconds)
                continue
            goal, cycle = claim
            try:
                progress = self._progress_context(mission_id)
                plan = self.planner.plan(goal, progress, mission_id=mission_id, cycle=cycle)
                self._store_plan(mission_id, worker_id, cycle, plan)
                emit(json.dumps({
                    "event": "plan_saved", "mission_id": mission_id,
                    "cycle": cycle, "state": plan.state,
                    "task_count": len(plan.tasks), "summary": plan.summary,
                }, ensure_ascii=False))
            except Exception:
                with self._transaction() as db:
                    db.execute("""
                        UPDATE development_missions
                        SET planning_owner='',planning_lease_until=NULL,updated_at=?
                        WHERE mission_id=? AND planning_owner=?
                    """, (time.time(), mission_id, worker_id))
                raise

        return self.get_mission(mission_id)


class ModelMissionPlanner:
    """Ask Core AI for the next actionable batch or an explicit completion verdict."""

    SYSTEM = """You are the continuing development planner for STREAMIOV.
The mission is persistent and may require any number of planning cycles. Never
declare completion merely because one batch finished. Evaluate the original
goal against the accumulated progress and actual task outcomes. If work remains,
return a focused next batch. If and only if every requested objective is
verified complete, return state=completed and no tasks. The engine enforces a separate testing-specialist final verification report before accepting completion.
Return exactly one JSON object:
{"state":"continue","summary":"what is verified and what comes next","tasks":[{"id":"short-id","specialist":"code","prompt":"actionable implementation task","depends_on":[]}]}
or {"state":"completed","summary":"evidence-based completion statement","tasks":[]}
Available roles: """ + ", ".join(specialist_names()) + """
Each batch may contain 1–12 tasks to fit one model response. This is not a
mission-wide task or cycle limit. IDs must be unique within the batch, 1–32
letters/digits/hyphens/underscores. Dependencies refer to IDs in this batch.
Do not plan public releases, production deployments, credential/OAuth/security
changes, payments, or external irreversible actions. Preserve existing work.
Do not treat a previous model claim as evidence; rely on recorded task results.
Use testing/repair specialists when verification or correction is needed."""

    def __init__(self, provider, *, max_tasks_per_batch: int = 12) -> None:
        if not 1 <= max_tasks_per_batch <= 12:
            raise ValueError("max_tasks_per_batch must be between 1 and 12.")
        self.provider = provider
        self.max_tasks_per_batch = max_tasks_per_batch

    def plan(self, goal: str, progress: str, *, mission_id: str, cycle: int) -> MissionPlan:
        messages = [{
            "role": "user",
            "content": (
                f"MISSION ID: {mission_id}\nPLANNING CYCLE: {cycle}\n"
                f"ORIGINAL GOAL:\n{goal}\n\nPERSISTED PROGRESS AND TASK OUTCOMES:\n{progress}\n\n"
                "Plan the next actionable work or declare verified completion."
            ),
        }]
        reply = self.provider.generate(system=self.SYSTEM, messages=messages)
        if not isinstance(reply.content, str) or len(reply.content) > 24000:
            raise MissionEngineError("Mission planner response is missing or exceeds 24 KB.")
        try:
            payload = json.loads(reply.content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise MissionEngineError("Mission planner must return valid JSON.") from exc
        if not isinstance(payload, dict) or set(payload) != {"state", "summary", "tasks"}:
            raise MissionEngineError("Mission plan must contain exactly state, summary and tasks.")
        if payload["state"] not in {"continue", "completed"}:
            raise MissionEngineError("Mission planner returned an unsupported state.")
        if not isinstance(payload["summary"], str) or not payload["summary"].strip():
            raise MissionEngineError("Mission planner summary is required.")
        raw_tasks = payload["tasks"]
        if not isinstance(raw_tasks, list) or len(raw_tasks) > self.max_tasks_per_batch:
            raise MissionEngineError("Mission planner returned an invalid task batch.")
        prefix = f"cycle-{cycle}"
        id_map: dict[str, str] = {}
        for item in raw_tasks:
            if not isinstance(item, dict) or set(item) != {"id", "specialist", "prompt", "depends_on"}:
                raise MissionEngineError("Each task must contain exactly id, specialist, prompt and depends_on.")
            local_id = item["id"]
            if not isinstance(local_id, str) or not local_id or len(local_id) > 32 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in local_id):
                raise MissionEngineError("Mission task IDs must be safe identifiers.")
            if local_id in id_map:
                raise MissionEngineError("Mission task IDs must be unique within a batch.")
            id_map[local_id] = f"{prefix}-{local_id}"
        tasks = []
        for item in raw_tasks:
            dependencies = item["depends_on"]
            if not isinstance(dependencies, list) or any(dep not in id_map for dep in dependencies):
                raise MissionEngineError("Mission task dependencies must refer to this batch.")
            if not isinstance(item["prompt"], str) or not item["prompt"].strip() or len(item["prompt"]) > 8000:
                raise MissionEngineError("Mission task prompts must contain 1–8000 characters.")
            get_specialist(item["specialist"])
            tasks.append(SpecialistTask(
                id_map[item["id"]], item["specialist"], item["prompt"].strip(),
                tuple(id_map[dep] for dep in dependencies),
            ))
        if payload["state"] == "continue" and not tasks:
            raise MissionEngineError("A continuing mission needs at least one actionable task.")
        if payload["state"] == "completed" and tasks:
            raise MissionEngineError("A completed mission cannot contain tasks.")
        return MissionPlan(payload["state"], payload["summary"].strip(), tuple(tasks))
