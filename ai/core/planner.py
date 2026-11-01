"""Fail-closed model planner that assigns bounded work to specialist roles."""
from __future__ import annotations

import json
import re
import uuid

from ai.core.orchestrator import SpecialistTask, TaskOrchestrator, TaskPlanError
from ai.providers.base import ModelProvider


MAX_PLAN_CHARS = 16_000
MAX_PLAN_TASKS = 12
PLAN_SYSTEM = """You are STREAMIOV Core, the task planner for a specialist development team.
Break the user's goal into a small dependency-aware plan for the available specialist roles:
core, code, game, design, gifts, testing, repair, integration, studio, server, general.
Return exactly one JSON object and no Markdown:
{"tasks":[{"id":"short-id","specialist":"code","prompt":"focused task","depends_on":[]}]}
Use 1–12 tasks. Each task must have a unique short id (letters, digits, hyphen, underscore; max 32 chars), one valid specialist, a focused actionable prompt (max 8000 chars), and a list of ids it depends on. Dependencies must refer only to tasks in this plan and must form a directed acyclic graph.
Keep independent work independent. Put prerequisites before dependent tasks where practical.
Do not include credentials, secrets, OAuth tokens, payment actions, production deployments, or requests to bypass platform permissions. Do not invent external capabilities. Assign only work that belongs to the specialist's documented mission. Planning does not authorize external, irreversible, legal, financial, or production actions."""


class PlannerError(ValueError):
    pass


class SpecialistPlanner:
    def __init__(self, provider: ModelProvider, *, max_tasks: int = MAX_PLAN_TASKS) -> None:
        if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or not 1 <= max_tasks <= MAX_PLAN_TASKS:
            raise ValueError(f"max_tasks must be between 1 and {MAX_PLAN_TASKS}.")
        self.provider = provider
        self.max_tasks = max_tasks

    def plan(self, goal: str, *, plan_id: str | None = None) -> list[SpecialistTask]:
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 8000:
            raise PlannerError("Goal must contain 1–8000 characters.")
        prefix = plan_id or uuid.uuid4().hex[:12]
        if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", prefix):
            raise PlannerError("plan_id must contain 1–32 safe identifier characters.")
        reply = self.provider.generate(
            system=PLAN_SYSTEM,
            messages=[{"role": "user", "content": goal.strip()}],
        )
        if not isinstance(reply.content, str) or len(reply.content) > MAX_PLAN_CHARS:
            raise PlannerError("Planner response is missing or exceeds the 16 KB limit.")
        try:
            payload = json.loads(reply.content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PlannerError("Planner response must be one valid JSON object; refusing to guess.") from exc
        if not isinstance(payload, dict) or set(payload) != {"tasks"} or not isinstance(payload["tasks"], list):
            raise PlannerError("Planner response must contain only a tasks array.")
        raw_tasks = payload["tasks"]
        if not 1 <= len(raw_tasks) <= self.max_tasks:
            raise PlannerError(f"Planner must return 1–{self.max_tasks} tasks.")

        id_map: dict[str, str] = {}
        for item in raw_tasks:
            if not isinstance(item, dict) or set(item) != {"id", "specialist", "prompt", "depends_on"}:
                raise PlannerError("Every planned task must contain exactly id, specialist, prompt and depends_on.")
            local_id = item["id"]
            if not isinstance(local_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", local_id):
                raise PlannerError("Task IDs must use 1–32 letters, digits, hyphens or underscores.")
            if local_id in id_map:
                raise PlannerError(f"Duplicate planner task ID: {local_id}")
            id_map[local_id] = f"{prefix}-{local_id}"

        tasks: list[SpecialistTask] = []
        for item in raw_tasks:
            dependencies = item["depends_on"]
            if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
                raise PlannerError("Task dependencies must be an array of task IDs.")
            unknown = [dep for dep in dependencies if dep not in id_map]
            if unknown:
                raise PlannerError(f"Unknown dependency IDs: {', '.join(unknown)}")
            prompt = item["prompt"]
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
                raise PlannerError("Every planned task needs a prompt of 1–8000 characters.")
            tasks.append(SpecialistTask(
                task_id=id_map[item["id"]],
                specialist=item["specialist"],
                prompt=prompt.strip(),
                depends_on=tuple(id_map[dep] for dep in dependencies),
            ))
        try:
            TaskOrchestrator(lambda _role: None, max_tasks=self.max_tasks)._validate_and_order(tuple(tasks))
        except (TaskPlanError, ValueError) as exc:
            raise PlannerError(f"Planner produced an invalid task graph: {exc}") from exc
        return tasks
