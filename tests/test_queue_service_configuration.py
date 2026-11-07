"""Regression checks for the shared host/worker systemd queue configuration."""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE_DB = "/var/lib/streamiov/queue.sqlite3"


class QueueServiceConfigurationTests(unittest.TestCase):
    def test_host_api_and_worker_use_the_same_persistent_queue(self):
        worker = (ROOT / "infrastructure/systemd/streamiov-opencode-core.service").read_text()
        host = (ROOT / "host/systemd/streamiov-host.service").read_text()

        self.assertIn(f"Environment=STREAMIOV_TASK_QUEUE_DB={QUEUE_DB}", worker)
        self.assertIn(f"--queue-db {QUEUE_DB}", worker)
        self.assertIn(f"Environment=STREAMIOV_TASK_QUEUE_DB={QUEUE_DB}", host)
        self.assertIn("EnvironmentFile=-/etc/streamiov/queue-admin.env", host)
        self.assertIn("StateDirectory=streamiov", worker)
        self.assertIn("StateDirectory=streamiov-host streamiov", host)
        self.assertIn("ReadWritePaths=/var/lib/streamiov", worker)
        self.assertIn("ReadWritePaths=/var/lib/streamiov", host)

    def test_worker_is_supervised_and_stops_with_sigterm(self):
        worker = (ROOT / "infrastructure/systemd/streamiov-opencode-core.service").read_text()
        self.assertIn("Restart=always", worker)
        self.assertIn("KillSignal=SIGTERM", worker)
        self.assertIn("TimeoutStopSec=120", worker)
        self.assertIn("NoNewPrivileges=true", worker)
        self.assertIn("ProtectSystem=strict", worker)


if __name__ == "__main__":
    unittest.main()
