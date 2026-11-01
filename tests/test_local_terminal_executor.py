from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.runtime.local_terminal_executor import (
    COMMAND_PROFILES,
    ExecutorError,
    LocalTerminalExecutor,
    _canonical,
    _redact,
    verify_signed_job,
)


KEY = b"test-signing-key-that-is-at-least-32-bytes"
DEVICE = "chromebook-dev-01"


def signed_job(**overrides):
    job = {
        "id": "job_12345678",
        "device_id": DEVICE,
        "profile": "git-status",
        "issued_at": 1000,
        "expires_at": 1100,
        "nonce": "0123456789abcdef",
        "args": {},
    }
    job.update(overrides)
    signature = hmac.new(KEY, _canonical(job), hashlib.sha256).hexdigest()
    return {"job": job, "signature": signature}


class VerifySignedJobTests(unittest.TestCase):
    def test_accepts_valid_bounded_job(self):
        result = verify_signed_job(signed_job(), KEY, DEVICE, now=1050)
        self.assertEqual(result["profile"], "git-status")

    def test_rejects_bad_signature(self):
        envelope = signed_job()
        envelope["signature"] = "0" * 64
        with self.assertRaisesRegex(ExecutorError, "signature"):
            verify_signed_job(envelope, KEY, DEVICE, now=1050)

    def test_rejects_other_device(self):
        with self.assertRaisesRegex(ExecutorError, "another device"):
            verify_signed_job(signed_job(), KEY, "different-device", now=1050)

    def test_rejects_expired_job(self):
        with self.assertRaisesRegex(ExecutorError, "expired"):
            verify_signed_job(signed_job(), KEY, DEVICE, now=1200)

    def test_rejects_arbitrary_command_arguments(self):
        envelope = signed_job(args={"command": "rm -rf ~"})
        with self.assertRaisesRegex(ExecutorError, "arguments"):
            verify_signed_job(envelope, KEY, DEVICE, now=1050)

    def test_rejects_unknown_profile(self):
        with self.assertRaisesRegex(ExecutorError, "Unknown command profile"):
            verify_signed_job(signed_job(profile="arbitrary-shell"), KEY, DEVICE, now=1050)

    def test_rejects_extra_schema_fields_even_when_signed(self):
        envelope = signed_job(shell="echo unsafe")
        with self.assertRaisesRegex(ExecutorError, "schema"):
            verify_signed_job(envelope, KEY, DEVICE, now=1050)


class RedactionTests(unittest.TestCase):
    def test_redacts_common_credentials(self):
        value = "Authorization: Bearer abc123 token=secret-value"
        result = _redact(value)
        self.assertNotIn("abc123", result)
        self.assertNotIn("secret-value", result)
        self.assertIn("[REDACTED]", result)


class LocalExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.workspace = self.home / "streamiov"
        self.workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        self.audit = self.workspace / "data/ai-development/local-executor.sqlite3"
        self.audit.parent.mkdir(parents=True)
        with patch.dict(os.environ, {"HOME": str(self.home)}):
            self.executor = LocalTerminalExecutor(
                workspace=self.workspace,
                device_id=DEVICE,
                control_url="https://streamiov-ai-worker.example.workers.dev",
                device_token="device-token-value-at-least-32-characters",
                signing_key=KEY,
                audit_db=self.audit,
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_only_fixed_profiles_exist(self):
        self.assertEqual(COMMAND_PROFILES, {"diagnostics", "git-status", "python-tests"})

    def test_executes_allowlisted_profile_and_records_digest(self):
        envelope = signed_job()
        with patch.object(self.executor, "_request", side_effect=[envelope, {"ok": True}]) as request:
            result = self.executor.run_once()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(len(result["result_sha256"]), 64)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].args[0], f"/v1/devices/{DEVICE}/jobs/job_12345678/complete")

    def test_refuses_replayed_job(self):
        envelope = signed_job()
        with patch.object(self.executor, "_request", return_value=envelope):
            self.executor.run_once()
            with self.assertRaisesRegex(ExecutorError, "Duplicate"):
                self.executor.run_once()

    def test_child_environment_does_not_include_device_credentials(self):
        envelope = signed_job()
        captured = {}
        original_run = subprocess.run

        def inspect_run(*args, **kwargs):
            captured.update(kwargs.get("env", {}))
            return original_run(*args, **kwargs)

        with patch.object(self.executor, "_request", side_effect=[envelope, {"ok": True}]), patch(
            "ai.runtime.local_terminal_executor.subprocess.run", side_effect=inspect_run
        ):
            result = self.executor.run_once()
        self.assertEqual(result["status"], "succeeded")
        self.assertNotIn("STREAMIOV_DEVICE_TOKEN", captured)
        self.assertNotIn("STREAMIOV_JOB_SIGNING_KEY", captured)


if __name__ == "__main__":
    unittest.main()
