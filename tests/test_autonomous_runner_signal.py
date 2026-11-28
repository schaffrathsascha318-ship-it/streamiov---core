"""Process-level regression coverage for graceful mission runner shutdown."""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "autonomous" / "run_issue.py"


@unittest.skipUnless(os.name == "posix", "POSIX signal delivery is required")
class AutonomousRunnerSignalTests(unittest.TestCase):
    def test_sigterm_stops_runner_cooperatively_and_checkpoints_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp, "mission.sqlite3")
            script = r"""
import importlib.util
from contextlib import closing
import sqlite3
import sys
import threading
from pathlib import Path

runner_path = Path(sys.argv[1])
database = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("streamiov_runner", runner_path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

with closing(sqlite3.connect(database)) as db:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE shutdown_state (value TEXT NOT NULL)")
    db.execute("INSERT INTO shutdown_state VALUES ('started')")
    db.commit()

stop = threading.Event()
try:
    def run_after_handlers_are_installed():
        print("READY", flush=True)
        return stop.wait(30)

    runner.run_with_signal_handlers(run_after_handlers_are_installed, stop)
    with closing(sqlite3.connect(database)) as db:
        db.execute("INSERT INTO shutdown_state VALUES ('stopped')")
        db.commit()
finally:
    runner.checkpoint_database(database)
"""
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(RUNNER), str(database)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.stdout.readline().strip(), "READY")
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, msg=f"stdout={stdout}\nstderr={stderr}")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)

            with closing(sqlite3.connect(database)) as db:
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
                rows = db.execute(
                    "SELECT value FROM shutdown_state ORDER BY rowid"
                ).fetchall()
                checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()

            self.assertEqual(integrity, "ok")
            self.assertEqual(rows, [("started",), ("stopped",)])
            self.assertEqual(checkpoint[0], 0, "WAL checkpoint reported a busy database")


if __name__ == "__main__":
    unittest.main()
