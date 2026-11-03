"""Bounded, dependency-aware orchestration across STREAMIOV AI specialists.

This runner executes an explicit task plan. It does not claim to be a persistent
background service or an autonomous model-based planner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from ai.specialists.registry import get_specialist


class AgentLike(Protocol):
    def run(self, task: str) -> str: ...


AgentFactory = Callable[[str], AgentLike]
TaskStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class SpecialistTask:
    task_id: str
    specialist: str
    prompt: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    specialist: str
    status: TaskStatus
    result: str = ""
    error: str = ""


class TaskPlanError(ValueError):
    pass


class TaskOrchestrator:
    """Execute a validated task DAG in dependency order, stopping dependants on failure."""

    def __init__(self, agent_factory: AgentFactory, *, max_tasks: int = 32) -> None:
        if not callable(agent_factory):
            raise TypeError("agent_factory must be callable")
        if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or not 1 <= max_tasks <= 128:
            raise ValueError("max_tasks must be between 1 and 128")
        self.agent_factory = agent_factory
        self.max_tasks = max_tasks

    def _validate_and_order(self, tasks: tuple[SpecialistTask, ...]) -> list[SpecialistTask]:
        if not tasks or len(tasks) > self.max_tasks:
            raise TaskPlanError(f"Task plan must contain 1–{self.max_tasks} tasks.")
        by_id: dict[str, SpecialistTask] = {}
        for task in tasks:
            if not isinstance(task, SpecialistTask):
                raise TaskPlanError("Every plan entry must be a SpecialistTask.")
            if not isinstance(task.task_id, str) or not task.task_id.strip() or len(task.task_id) > 64:
                raise TaskPlanError("Every task needs a non-empty ID of at most 64 characters.")
            if task.task_id in by_id:
                raise TaskPlanError(f"Duplicate task ID: {task.task_id}")
            if not isinstance(task.prompt, str) or not task.prompt.strip() or len(task.prompt) > 8000:
                raise TaskPlanError(f"Task {task.task_id} needs a prompt of 1–8000 characters.")
            get_specialist(task.specialist)
            if not isinstance(task.depends_on, tuple) or any(not isinstance(dep, str) for dep in task.depends_on):
                raise TaskPlanError(f"Task {task.task_id} dependencies must be a tuple of task IDs.")
            if task.task_id in task.depends_on or len(set(task.depends_on)) != len(task.depends_on):
                raise TaskPlanError(f"Task {task.task_id} has a self-dependency or duplicate dependency.")
            by_id[task.task_id] = task

        for task in tasks:
            missing = [dep for dep in task.depends_on if dep not in by_id]
            if missing:
                raise TaskPlanError(f"Task {task.task_id} has unknown dependencies: {', '.join(missing)}")

        ordered: list[SpecialistTask] = []
        pending = list(tasks)
        completed: set[str] = set()
        while pending:
            ready = [task for task in pending if set(task.depends_on).issubset(completed)]
            if not ready:
                raise TaskPlanError("Task plan contains a dependency cycle.")
            for task in ready:
                ordered.append(task)
                completed.add(task.task_id)
                pending.remove(task)
        return ordered

    def run(self, tasks: list[SpecialistTask] | tuple[SpecialistTask, ...]) -> list[TaskResult]:
        """Validate the entire plan before work, then execute tasks in stable DAG order."""
        ordered = self._validate_and_order(tuple(tasks))
        results: dict[str, TaskResult] = {}
        for task in ordered:
            failed_dependencies = [dep for dep in task.depends_on if results[dep].status != "succeeded"]
            if failed_dependencies:
                results[task.task_id] = TaskResult(
                    task_id=task.task_id,
                    specialist=task.specialist,
                    status="skipped",
                    error=f"Skipped because dependencies did not succeed: {', '.join(failed_dependencies)}",
                )
                continue
            try:
                output = self.agent_factory(task.specialist).run(task.prompt)
                if not isinstance(output, str):
                    raise TypeError("Specialist agent returned a non-text result.")
                results[task.task_id] = TaskResult(task.task_id, task.specialist, "succeeded", result=output)
            except Exception as exc:
                results[task.task_id] = TaskResult(
                    task_id=task.task_id,
                    specialist=task.specialist,
                    status="failed",
                    error=f"{type(exc).__name__}: {str(exc)[:500]}",
                )
        return [results[task.task_id] for task in ordered]
