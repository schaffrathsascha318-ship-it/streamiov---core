"""Sequential, validated coordination of Streamiov development specialists."""

from dataclasses import dataclass
from pathlib import Path

from ai.core.agent import DevelopmentAgent
from ai.core.specialists import SPECIALISTS


@dataclass(frozen=True)
class CoordinatorStep:
    role: str
    task: str


@dataclass(frozen=True)
class CoordinatorResult:
    role: str
    result: str


class CoordinatorError(RuntimeError):
    def __init__(self, failed_role, completed, cause):
        self.failed_role = failed_role
        self.completed = tuple(completed)
        self.cause = cause
        super().__init__(
            f"Specialist {failed_role!r} failed after "
            f"{len(self.completed)} completed step(s): {cause}"
        )


class DevelopmentCoordinator:
    """Run a complete, prevalidated specialist plan in sequence."""

    def __init__(self, provider, project_root, max_steps=12):
        if type(max_steps) is not int or not 1 <= max_steps <= 30:
            raise ValueError("max_steps must be an integer between 1 and 30")

        self.provider = provider
        self.project_root = Path(project_root)
        self.max_steps = max_steps

    def validate_plan(self, steps):
        if not isinstance(steps, (list, tuple)) or not steps:
            raise ValueError("A non-empty plan is required.")

        if len(steps) > len(SPECIALISTS):
            raise ValueError("Plan exceeds the number of available specialists.")

        seen = set()

        for step in steps:
            if not isinstance(step, CoordinatorStep):
                raise ValueError("Every entry must be a CoordinatorStep.")

            if step.role not in SPECIALISTS:
                raise ValueError(f"Unknown specialist: {step.role!r}")

            if step.role in seen:
                raise ValueError(f"Duplicate specialist: {step.role!r}")

            if not isinstance(step.task, str) or not step.task.strip():
                raise ValueError("Every task must contain text.")

            if len(step.task) > 8000:
                raise ValueError("Tasks must not exceed 8000 characters.")

            seen.add(step.role)

    def run(self, steps):
        self.validate_plan(steps)
        completed = []

        for step in steps:
            agent = DevelopmentAgent(
                provider=self.provider,
                project_root=self.project_root,
                max_steps=self.max_steps,
                specialist=step.role,
            )

            try:
                result = agent.run(step.task)
            except Exception as exc:
                raise CoordinatorError(
                    step.role, completed, exc
                ) from exc

            completed.append(
                CoordinatorResult(step.role, result)
            )

        return tuple(completed)
