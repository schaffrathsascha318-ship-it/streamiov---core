"""Outbound-only, allowlisted Chromebook terminal executor for STREAMIOV.

The cloud may select a named profile; it can never supply a command, shell
fragment, path, executable, environment variable, or arbitrary argument.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

MAX_OUTPUT = 16_000
MAX_JOB_TTL = 300
MIN_FREE_BYTES = 250 * 1024 * 1024
POLL_SECONDS = 10
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{3,80}$")
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+"),
    re.compile(r"(?i)((?:token|secret|password|api[_-]?key)\s*[=:]\s*)[^\s,;]+"),
)


class ExecutorError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _redact(value: str) -> str:
    result = value
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(r"\1[REDACTED]", result)
    return result[-MAX_OUTPUT:]


def _https_worker_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not (parsed.hostname == "workers.dev" or parsed.hostname.endswith(".workers.dev"))
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ("", "/") or parsed.port not in (None, 443)
    ):
        raise ExecutorError("Control-plane URL must be an HTTPS workers.dev origin.")
    return value.rstrip("/")


def verify_signed_job(envelope: dict, signing_key: bytes, device_id: str, now: int | None = None) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"job", "signature"}:
        raise ExecutorError("Malformed signed job envelope.")
    job, signature = envelope["job"], envelope["signature"]
    if not isinstance(job, dict) or not isinstance(signature, str):
        raise ExecutorError("Malformed job or signature.")
    expected = hmac.new(signing_key, _canonical(job), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ExecutorError("Job signature is invalid.")
    required = {"id", "device_id", "profile", "issued_at", "expires_at", "nonce", "args"}
    if set(job) != required:
        raise ExecutorError("Job schema is not allowlisted.")
    if not isinstance(job["id"], str) or not JOB_ID_RE.fullmatch(job["id"]):
        raise ExecutorError("Invalid job identifier.")
    if job["device_id"] != device_id:
        raise ExecutorError("Job is assigned to another device.")
    if not isinstance(job["profile"], str) or job["profile"] not in COMMAND_PROFILES:
        raise ExecutorError("Unknown command profile.")
    if job["args"] != {}:
        raise ExecutorError("Remote command arguments are not permitted.")
    nonce = job["nonce"]
    if not isinstance(nonce, str) or not 16 <= len(nonce) <= 128:
        raise ExecutorError("Invalid job nonce.")
    issued, expires = job["issued_at"], job["expires_at"]
    if isinstance(issued, bool) or not isinstance(issued, int) or isinstance(expires, bool) or not isinstance(expires, int):
        raise ExecutorError("Invalid job timestamps.")
    current = int(time.time()) if now is None else now
    if issued > current + 30 or expires < current or expires <= issued or expires - issued > MAX_JOB_TTL:
        raise ExecutorError("Job is expired or outside the permitted lifetime.")
    return job


def _commands(root: Path) -> dict[str, tuple[str, ...]]:
    python = sys.executable
    return {
        "diagnostics": (
            (python, "--version"),
            ("git", "--version"),
            ("git", "status", "--short", "--branch"),
        ),
        "git-status": (("git", "status", "--short", "--branch"),),
        "python-tests": ((python, "-m", "unittest", "discover", "-s", "tests", "-v"),),
    }


COMMAND_PROFILES = {"diagnostics", "git-status", "python-tests"}


class LocalTerminalExecutor:
    def __init__(
        self, *, workspace: Path, device_id: str, control_url: str, device_token: str,
        signing_key: bytes, audit_db: Path, timeout_seconds: int = 180,
    ) -> None:
        raw_workspace = Path(workspace).expanduser()
        if raw_workspace.is_symlink():
            raise ExecutorError("Workspace symlinks are not permitted.")
        expected_workspace = (Path.home() / "streamiov").resolve()
        self.workspace = raw_workspace.resolve(strict=True)
        if self.workspace != expected_workspace or not self.workspace.is_dir():
            raise ExecutorError("Workspace must be exactly the existing ~/streamiov directory.")
        self.device_id = device_id
        if not DEVICE_RE.fullmatch(device_id):
            raise ExecutorError("Invalid device identifier.")
        self.control_url = _https_worker_url(control_url)
        if len(device_token) < 32 or len(signing_key) < 32:
            raise ExecutorError("Device token and signing key must each contain at least 32 characters.")
        self.device_token = device_token
        self.signing_key = signing_key
        if not 10 <= timeout_seconds <= 900:
            raise ExecutorError("Timeout must be between 10 and 900 seconds.")
        self.timeout_seconds = timeout_seconds
        self.audit_db = Path(audit_db).expanduser()
        expected_audit_root = self.workspace / "data" / "ai-development"
        resolved_parent = self.audit_db.parent.resolve()
        if resolved_parent != expected_audit_root.resolve() or self.audit_db.is_symlink():
            raise ExecutorError("Audit database must stay inside data/ai-development.")
        self.audit_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_audit()

    def _connect(self):
        connection = sqlite3.connect(self.audit_db, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_audit(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS executions (
                job_id TEXT PRIMARY KEY, profile TEXT NOT NULL, status TEXT NOT NULL,
                started_at INTEGER NOT NULL, finished_at INTEGER, exit_code INTEGER,
                result_sha256 TEXT, output TEXT NOT NULL DEFAULT ''
            )""")
        try:
            os.chmod(self.audit_db, 0o600)
        except OSError:
            pass

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = _canonical(payload) if payload is not None else None
        request = urllib.request.Request(
            self.control_url + path, data=data,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.device_token,
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read(64 * 1024)
            result = json.loads(body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ExecutorError("Control-plane request failed; no command was executed.") from exc
        if not isinstance(result, dict):
            raise ExecutorError("Control plane returned an invalid response.")
        return result

    def _resource_check(self) -> None:
        free = shutil.disk_usage(self.workspace).free
        if free < MIN_FREE_BYTES:
            raise ExecutorError(f"Disk guard stopped execution: only {free} bytes are free.")
        if self.workspace.is_symlink():
            raise ExecutorError("Workspace symlinks are not permitted.")

    def _already_seen(self, job_id: str) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT status FROM executions WHERE job_id=?", (job_id,)).fetchone()
            return row is not None

    def _execute_profile(self, profile: str) -> tuple[int, str]:
        self._resource_check()
        started = time.monotonic()
        outputs = []
        child_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home())}
        for argv in _commands(self.workspace)[profile]:
            remaining = self.timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise ExecutorError("Profile exceeded its overall timeout.")
            try:
                completed = subprocess.run(
                    list(argv), cwd=self.workspace, env=child_env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, errors="replace", timeout=remaining, check=False,
                    shell=False, close_fds=True,
                )
            except subprocess.TimeoutExpired:
                outputs.append(f"$ {argv[0]} [TIMEOUT]")
                return 124, _redact("\n".join(outputs))
            stdout = _redact(completed.stdout or "")
            stderr = _redact(completed.stderr or "")
            outputs.append(f"$ {' '.join(argv)}\nexit_code={completed.returncode}\n{stdout}\n{stderr}")
            if completed.returncode != 0:
                return completed.returncode, _redact("\n".join(outputs))
        return 0, _redact("\n".join(outputs))

    def run_once(self) -> dict:
        claim = self._request(f"/v1/devices/{self.device_id}/jobs/claim", {"device_id": self.device_id})
        if claim.get("status") == "idle":
            return {"status": "idle"}
        job = verify_signed_job(claim, self.signing_key, self.device_id)
        if self._already_seen(job["id"]):
            raise ExecutorError("Duplicate or previously interrupted job refused; manual audit required.")
        started = int(time.time())
        with self._connect() as db:
            db.execute(
                "INSERT INTO executions(job_id,profile,status,started_at) VALUES(?,?,?,?)",
                (job["id"], job["profile"], "running", started),
            )
        try:
            exit_code, output = self._execute_profile(job["profile"])
            status = "succeeded" if exit_code == 0 else "failed"
        except Exception as exc:
            exit_code, output, status = 1, _redact(str(exc)), "failed"
        digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
        finished = int(time.time())
        with self._connect() as db:
            db.execute(
                "UPDATE executions SET status=?,finished_at=?,exit_code=?,result_sha256=?,output=? WHERE job_id=?",
                (status, finished, exit_code, digest, output, job["id"]),
            )
        result = {
            "job_id": job["id"], "device_id": self.device_id, "profile": job["profile"],
            "status": status, "exit_code": exit_code, "started_at": started,
            "finished_at": finished, "duration_seconds": max(0, finished - started),
            "result_sha256": digest, "output": output,
        }
        self._request(f"/v1/devices/{self.device_id}/jobs/{job['id']}/complete", result)
        return result

    def doctor(self) -> dict:
        self._resource_check()
        return {
            "workspace": str(self.workspace),
            "device_id": self.device_id,
            "control_plane": self.control_url,
            "disk_free_bytes": shutil.disk_usage(self.workspace).free,
            "audit_db": str(self.audit_db),
            "profiles": sorted(COMMAND_PROFILES),
            "ready": True,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded STREAMIOV Chromebook terminal executor")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--doctor", action="store_true")
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--workspace", default=str(Path.home() / "streamiov"))
    parser.add_argument("--audit-db", default=str(Path.home() / "streamiov/data/ai-development/local-executor.sqlite3"))
    args = parser.parse_args(argv)
    try:
        device_id = os.environ["STREAMIOV_DEVICE_ID"]
        control_url = os.environ["STREAMIOV_CONTROL_URL"]
        device_token = os.environ["STREAMIOV_DEVICE_TOKEN"]
        signing_key = os.environ["STREAMIOV_JOB_SIGNING_KEY"].encode("utf-8")
        executor = LocalTerminalExecutor(
            workspace=Path(args.workspace), device_id=device_id, control_url=control_url,
            device_token=device_token, signing_key=signing_key,
            audit_db=Path(args.audit_db),
        )
        if args.doctor:
            print(json.dumps(executor.doctor(), ensure_ascii=False))
            return 0
        if args.once:
            print(json.dumps(executor.run_once(), ensure_ascii=False))
            return 0
        while True:
            try:
                result = executor.run_once()
                print(json.dumps(result, ensure_ascii=False), flush=True)
            except ExecutorError as exc:
                print(json.dumps({"status": "error", "detail": str(exc)}), file=sys.stderr, flush=True)
                time.sleep(POLL_SECONDS)
                continue
            if result.get("status") == "idle":
                time.sleep(POLL_SECONDS)
    except (KeyError, ExecutorError, OSError) as exc:
        print(json.dumps({"status": "not_ready", "detail": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
