"""Ordered provider routing for the Streamiov Core model runtime.

Only explicitly configured providers are used. A failed provider (including a
Cloudflare 429 quota response) cannot prevent the router from trying the next
configured local/self-hosted provider.
"""
from __future__ import annotations

import threading
import time
from typing import Iterable

from .base import ModelReply, ModelProvider
from .local_http import ProviderError


LOCAL_PROVIDER_KINDS = frozenset({"ollama", "openai-compatible-local"})
SIMPLE_TASK_ROLES = frozenset({
    "planning",
    "research",
    "homepage",
    "ai_design_agent",
})
DEFAULT_RECOVERY_COOLDOWN_SECONDS = 6 * 60 * 60
MAX_RECOVERY_COOLDOWN_SECONDS = 24 * 60 * 60


class ProviderRecoveryError(ProviderError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: str = "provider_unavailable",
        retry_after_seconds: float = 0,
        providers_tried: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.retry_after_seconds = max(float(retry_after_seconds), 0.0)
        self.providers_tried = tuple(providers_tried)


def _detail(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:400] or type(exc).__name__


def _failure_class(exc: BaseException) -> str:
    explicit = getattr(exc, "failure_class", "")
    if isinstance(exc, ProviderRecoveryError) and explicit:
        return explicit
    if isinstance(explicit, str) and explicit:
        return explicit
    lowered = _detail(exc).lower()
    if (
        "daily_ai_limit_reached" in lowered
        or "daily free allocation" in lowered
        or "quota" in lowered
        or "429" in lowered
    ):
        return "quota"
    if "401" in lowered or "unauthorized" in lowered or "bearer token" in lowered:
        return "auth"
    if "timeout" in lowered or "timed out" in lowered or "deadline exceeded" in lowered:
        return "timeout"
    return "error"


def _is_recoverable_failure(failure_class: str) -> bool:
    return failure_class in {"quota", "throttle", "cooldown"}


class ProviderRouter:
    """Try configured providers in order and expose a secret-free health report."""

    def __init__(
        self,
        providers: Iterable[tuple[str, ModelProvider]],
        *,
        recovery_cooldown_seconds: float = DEFAULT_RECOVERY_COOLDOWN_SECONDS,
        max_recovery_cooldown_seconds: float = MAX_RECOVERY_COOLDOWN_SECONDS,
    ) -> None:
        configured = list(providers)
        if not configured:
            raise ProviderError("At least one Streamiov model provider must be configured.")
        names = [name for name, _provider in configured]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ProviderError("Provider names must be non-empty strings.")
        if len(set(names)) != len(names):
            raise ProviderError("A model provider may only appear once in the provider order.")
        if any(not callable(getattr(provider, "generate", None)) for _name, provider in configured):
            raise ProviderError("Every configured model provider must implement generate().")
        if recovery_cooldown_seconds <= 0 or max_recovery_cooldown_seconds <= 0:
            raise ProviderError("Provider recovery cooldowns must be positive.")
        self.providers = configured
        self.recovery_cooldown_seconds = min(
            float(recovery_cooldown_seconds), float(max_recovery_cooldown_seconds)
        )
        self.max_recovery_cooldown_seconds = float(max_recovery_cooldown_seconds)
        self._lock = threading.Lock()
        self._cooldown_until: dict[str, float] = {}

    def _cooldown_remaining(self, name: str, now: float | None = None) -> float:
        moment = time.time() if now is None else now
        with self._lock:
            return max(self._cooldown_until.get(name, 0.0) - moment, 0.0)

    def _set_cooldown(self, name: str, exc: BaseException, now: float) -> float:
        retry_after = getattr(exc, "retry_after_seconds", 0)
        try:
            retry_after = float(retry_after)
        except (TypeError, ValueError):
            retry_after = 0.0
        delay = min(
            max(retry_after, self.recovery_cooldown_seconds),
            self.max_recovery_cooldown_seconds,
        )
        with self._lock:
            self._cooldown_until[name] = now + delay
        return delay

    def check_ready(self) -> dict:
        statuses = []
        for name, provider in self.providers:
            check = getattr(provider, "check_ready", None)
            if not callable(check):
                statuses.append({
                    "provider": name,
                    "ready": False,
                    "reachable": False,
                    "model_available": False,
                    "cooldown_remaining_seconds": 0,
                    "detail": "Provider does not expose a health check.",
                })
                continue
            try:
                status = check()
                if not isinstance(status, dict):
                    raise ProviderError("Provider health response must be an object.")
                statuses.append({
                    **status,
                    "provider": name,
                    "cooldown_remaining_seconds": int(self._cooldown_remaining(name)),
                })
            except ProviderError as exc:
                statuses.append({
                    "provider": name,
                    "ready": False,
                    "reachable": False,
                    "model_available": False,
                    "cooldown_remaining_seconds": int(self._cooldown_remaining(name)),
                    "detail": f"Health check failed: {type(exc).__name__}.",
                })
        active = next((item["provider"] for item in statuses if item.get("ready") is True), None)
        return {
            "provider": "streamiov-provider-router",
            "ready": active is not None,
            "active_provider": active,
            "providers": statuses,
            "detail": "A configured model provider is ready." if active else "No configured model provider is ready.",
        }

    def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        allowed_providers: Iterable[str] | None = None,
    ) -> ModelReply:
        now = time.time()
        allowed = None if allowed_providers is None else set(allowed_providers)
        eligible = [
            (name, provider) for name, provider in self.providers
            if allowed is None or name in allowed
        ]
        if not eligible:
            raise ProviderRecoveryError(
                "No model provider is permitted for this task [failure_class=provider_capability].",
                failure_class="provider_capability",
            )
        failures = []
        failure_classes = []
        retry_after = 0.0
        for name, provider in eligible:
            remaining = self._cooldown_remaining(name, now)
            if remaining > 0:
                retry_after = max(retry_after, remaining)
                failures.append(f"{name}: recovery cooldown active for {int(remaining)}s")
                failure_classes.append("cooldown")
                continue
            try:
                reply = provider.generate(system=system, messages=messages)
                if not isinstance(reply, ModelReply):
                    raise ProviderError("Provider returned an invalid model reply.")
            except ProviderError as exc:
                failure_class = _failure_class(exc)
                failure_classes.append(failure_class)
                if _is_recoverable_failure(failure_class):
                    retry_after = max(retry_after, self._set_cooldown(name, exc, now))
                failures.append(f"{name}: {_detail(exc)}")
                continue
            with self._lock:
                self._cooldown_until.pop(name, None)
            return reply
        if failure_classes and all(_is_recoverable_failure(item) for item in failure_classes):
            failure_class = "provider_quota_all"
        else:
            failure_class = "provider_unavailable"
        suffix = (
            f" Retry after {int(retry_after)}s."
            if failure_class == "provider_quota_all" and retry_after > 0
            else ""
        )
        raise ProviderRecoveryError(
            "All configured Streamiov model providers failed "
            f"[failure_class={failure_class}].{suffix} " + " | ".join(failures),
            failure_class=failure_class,
            retry_after_seconds=retry_after,
            providers_tried=[name for name, _ in eligible],
        )


class TaskScopedProvider:
    def __init__(
        self,
        router: ProviderRouter,
        allowed_providers: Iterable[str],
        *,
        max_actions: int | None = None,
    ) -> None:
        available = {name for name, _ in router.providers}
        allowed = tuple(dict.fromkeys(item for item in allowed_providers if item in available))
        if not allowed:
            raise ProviderError("Task-scoped providers must allow at least one configured provider.")
        self.router = router
        self.allowed_providers = allowed
        self.max_actions = max_actions

    def check_ready(self) -> dict:
        report = self.router.check_ready()
        allowed = set(self.allowed_providers)
        report["allowed_providers"] = list(self.allowed_providers)
        report["providers"] = [
            item for item in report.get("providers", []) if item.get("provider") in allowed
        ]
        report["active_provider"] = next(
            (item["provider"] for item in report["providers"] if item.get("ready") is True), None
        )
        report["ready"] = report["active_provider"] is not None
        return report

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        return self.router.generate(
            system=system,
            messages=messages,
            allowed_providers=self.allowed_providers,
        )


def provider_for_role(provider, role: str):
    """Restrict free loopback models to explicitly eligible, low-risk tasks."""
    if isinstance(provider, TaskScopedProvider):
        provider = provider.router
    if not isinstance(provider, ProviderRouter):
        return provider
    names = tuple(name for name, _ in provider.providers)
    if not any(name in LOCAL_PROVIDER_KINDS for name in names):
        return provider
    local_recovery = role in SIMPLE_TASK_ROLES or "LOCAL_RECOVERY_ELIGIBLE" in role
    allowed = names
    if not local_recovery:
        allowed = tuple(name for name in names if name not in LOCAL_PROVIDER_KINDS)
        if not allowed:
            return provider
        return TaskScopedProvider(provider, allowed)
    return TaskScopedProvider(provider, allowed, max_actions=12)
