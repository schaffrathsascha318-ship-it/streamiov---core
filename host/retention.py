"""Optional, owner-controlled schedule for local forum data retention.

Retention never starts automatically from this file: the checked-in policy is
disabled and automatic deletion requires an explicit, locally stored opt-in.
The scheduler only calls the already reviewed, transactional
``ForumStore.apply_retention`` path and keeps a bounded private state file.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from host.forum import ForumError, ForumStore


DEFAULT_POLICY_PATH = (Path(__file__).resolve().parent.parent / "infrastructure" /
                       "forum" / "retention-policy.json")
STATE_NAME = "forum-retention-schedule.json"
STATE_ROOT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$")
MIN_INTERVAL_MINUTES = 60
MAX_INTERVAL_MINUTES = 10080


def load_retention_policy(policy_path: Path | str | None = None) -> dict:
    """Load and strictly validate the local retention schedule policy."""
    path = Path(policy_path).expanduser().resolve() if policy_path else DEFAULT_POLICY_PATH
    policy = {
        "enabled": False,
        "interval_seconds": 86400,
        "state_root": "forum-retention",
        "source": str(path),
        "error": None,
    }
    try:
        if path.is_symlink() or not path.is_file():
            raise ForumError("Retention policy file is missing or unsafe.")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ForumError) as exc:
        policy["error"] = "Retention policy is unreadable: " + str(exc)[:160]
        return policy
    if not isinstance(raw, dict):
        policy["error"] = "Retention policy must be an object."
        return policy
    schedule = raw.get("schedule")
    if not isinstance(schedule, dict):
        policy["error"] = "Retention policy has no local schedule."
        return policy
    enabled = schedule.get("enabled", False)
    interval = schedule.get("interval_minutes", 1440)
    state_root = schedule.get("state_root", "forum-retention")
    if not isinstance(enabled, bool):
        policy["error"] = "Retention schedule enabled flag must be boolean."
        return policy
    if (not isinstance(interval, int) or isinstance(interval, bool)
            or not MIN_INTERVAL_MINUTES <= interval <= MAX_INTERVAL_MINUTES):
        policy["error"] = ("Retention schedule interval must be "
                           f"{MIN_INTERVAL_MINUTES} to {MAX_INTERVAL_MINUTES} minutes.")
        return policy
    if not isinstance(state_root, str) or not STATE_ROOT_PATTERN.fullmatch(state_root):
        policy["error"] = "Retention schedule state root must be a simple local directory name."
        return policy
    policy.update({
        "enabled": enabled,
        "interval_seconds": interval * 60,
        "state_root": state_root,
        "error": None,
    })
    return policy


class ForumRetentionScheduler:
    """Run the forum retention policy on an explicit local schedule."""

    def __init__(self, data_dir: Path, policy_path: Path | str | None = None,
                 policy: dict | None = None, store_factory=None, now=None):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.policy = dict(policy) if policy is not None else load_retention_policy(policy_path)
        self.root = self.data_dir / str(self.policy.get("state_root", "forum-retention"))
        self.state_path = self.root / STATE_NAME
        self._store_factory = store_factory or ForumStore
        self.now = now if callable(now) else time.time
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _default_state() -> dict:
        return {
            "schema_version": 1,
            "last_run_at": None,
            "last_success_at": None,
            "next_run_at": None,
            "last_result": {},
            "last_error": None,
            "state_error": None,
            "run_count": 0,
            "failure_count": 0,
        }

    def _load_state(self) -> dict:
        state = self._default_state()
        if not self.state_path.exists():
            return state
        if self.state_path.is_symlink() or not self.state_path.is_file():
            state["state_error"] = "Retention schedule state is unsafe."
            return state
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state["state_error"] = "Retention schedule state is unreadable."
            return state
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            state["state_error"] = "Retention schedule state has an unsupported version."
            return state
        for key in ("last_run_at", "last_success_at", "next_run_at"):
            value = raw.get(key)
            if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
                state[key] = value
            else:
                state["state_error"] = "Retention schedule timestamps are invalid."
                return state
        for key in ("run_count", "failure_count"):
            value = raw.get(key, 0)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                state[key] = value
            else:
                state["state_error"] = "Retention schedule counters are invalid."
                return state
        last_result = raw.get("last_result", {})
        if isinstance(last_result, dict) and len(last_result) <= 12:
            state["last_result"] = {str(key): str(value)[:120] for key, value in last_result.items()}
        else:
            state["state_error"] = "Retention schedule result is invalid."
            return state
        last_error = raw.get("last_error")
        state["last_error"] = str(last_error)[:240] if isinstance(last_error, str) else None
        return state

    def _write_state(self, state: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.root / (STATE_NAME + "." + secrets.token_hex(6) + ".tmp")
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
                                 encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.state_path)
            os.chmod(self.state_path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _iso(value) -> str | None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    def status(self) -> dict:
        with self._lock:
            state = self._load_state()
            current = self.now()
            return {
                "ok": self.policy.get("error") is None and state.get("state_error") is None,
                "policy": {
                    "enabled": self.policy.get("enabled") is True,
                    "interval_seconds": self.policy.get("interval_seconds"),
                    "state_root": self.policy.get("state_root"),
                    "error": self.policy.get("error"),
                },
                "state": {
                    "last_run_at": self._iso(state.get("last_run_at")),
                    "last_success_at": self._iso(state.get("last_success_at")),
                    "next_run_at": self._iso(state.get("next_run_at")),
                    "last_result": state.get("last_result", {}),
                    "last_error": state.get("last_error"),
                    "state_error": state.get("state_error"),
                    "run_count": state.get("run_count", 0),
                    "failure_count": state.get("failure_count", 0),
                },
                "due_now": (self.policy.get("enabled") is True
                            and (state.get("next_run_at") is None
                                 or current >= state.get("next_run_at"))),
                "legal_status": "OWNER_AND_LEGAL_REVIEW_REQUIRED_BEFORE_ENABLE",
                "production_status": "NOT_VERIFIED",
            }

    def run_once(self, force: bool = False, at: float | None = None) -> dict:
        """Apply the reviewed retention policy once; force bypasses the clock."""
        with self._lock:
            current = self.now() if at is None else float(at)
            if not force and self.policy.get("enabled") is not True:
                return {"ok": True, "ran": False, "reason": "disabled", "status": self.status()}
            state = self._load_state()
            next_run = state.get("next_run_at")
            if not force and next_run is not None and current < next_run:
                return {"ok": True, "ran": False, "reason": "not_due", "status": self.status()}
            if self.policy.get("error"):
                return {"ok": False, "ran": True, "error": self.policy["error"],
                        "status": self.status()}
            if state.get("state_error"):
                return {"ok": False, "ran": True, "error": state["state_error"],
                        "status": self.status()}
            interval = int(self.policy.get("interval_seconds", 86400))
            state["last_run_at"] = current
            state["next_run_at"] = current + interval
            state["run_count"] = int(state.get("run_count", 0)) + 1
            try:
                result = self._store_factory(self.data_dir).apply_retention(now=int(current))
                deleted = result.get("deleted", {})
                report = {
                    "ok": True,
                    "ran": True,
                    "deleted": {str(key): int(value) for key, value in deleted.items()},
                    "next_run_at": self._iso(state["next_run_at"]),
                }
                state["last_success_at"] = current
                state["last_error"] = None
                state["last_result"] = {
                    "ok": True,
                    "deleted": sum(int(value) for value in deleted.values()),
                }
            except (ForumError, OSError, sqlite3.Error) as exc:
                message = str(exc)[:240]
                report = {"ok": False, "ran": True, "error": message,
                          "next_run_at": self._iso(state["next_run_at"])}
                state["failure_count"] = int(state.get("failure_count", 0)) + 1
                state["last_error"] = message
                state["last_result"] = {"ok": False, "error": message}
            self._write_state(state)
            report["status"] = self.status()
            return report

    def start(self) -> bool:
        if self.policy.get("enabled") is not True or self.policy.get("error"):
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="streamiov-forum-retention",
                                            daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _loop(self) -> None:
        interval = max(60, min(300, int(self.policy.get("interval_seconds", 86400))))
        while not self._stop.wait(interval):
            try:
                self.run_once()
            except (ForumError, OSError, sqlite3.Error):
                continue
