import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "infrastructure" / "systemd" / "streamiov-ai-chief-supervisor.service.example"
ENV_EXAMPLE = ROOT / "infrastructure" / "systemd" / "streamiov-ai-chief.env.example"
DOC = ROOT / "docs" / "ai-development" / "ai-chief-supervisor-service.md"


class AIChiefSupervisorServiceTests(unittest.TestCase):
    def test_service_runs_the_persistent_supervisor_as_a_restricted_user(self):
        service = SERVICE.read_text(encoding="utf-8")
        unit_section = service.split("[Service]", 1)[0]
        self.assertIn("StartLimitIntervalSec=300", unit_section)
        self.assertIn("StartLimitBurst=5", unit_section)
        for required in (
            "User=streamiov",
            "Group=streamiov",
            "EnvironmentFile=/etc/streamiov/ai-chief.env",
            'ExecStartPre=/usr/bin/test -n "${STREAMIOV_PROJECT_GOAL}"',
            "--project-supervisor-run",
            "--mission-db /var/lib/streamiov/ai-missions.sqlite3",
            "--learning-db /var/lib/streamiov/verified-learning.sqlite3",
            "--full-project-development",
            "--allow-self-modification",
            "Restart=always",
            "RestartSec=10",
            "KillSignal=SIGTERM",
            "TimeoutStopSec=90",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ReadWritePaths=/opt/streamiov /var/lib/streamiov",
            "UMask=0077",
        ):
            with self.subTest(required=required):
                self.assertIn(required, service)

    def test_provider_template_uses_existing_streamiov_ai_worker_without_real_secrets(self):
        env = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("STREAMIOV_MODEL_PROVIDER=cloudflare-workers-ai", env)
        self.assertIn("STREAMIOV_MODEL=@cf/zai-org/glm-4.7-flash", env)
        self.assertIn("STREAMIOV_MODEL_URL=https://REPLACE_WITH_EXISTING_STREAMIOV_AI_WORKER.workers.dev", env)
        self.assertIn("STREAMIOV_AI_WORKER_TOKEN=REPLACE_WITH_PRIVATE_AI_WORKER_TOKEN", env)
        self.assertIn("STREAMIOV_PROJECT_GOAL=", env)
        self.assertNotIn("ghp_", env)
        self.assertNotIn("sk-", env)
        self.assertNotIn("STREAMIOV_API_TOKEN=", env)

    def test_documentation_keeps_installation_and_production_actions_explicit(self):
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("source-only", doc.lower())
        self.assertIn("does not install or enable itself", doc)
        self.assertIn("does not", doc)
        self.assertIn("systemctl enable --now streamiov-ai-chief-supervisor.service", doc)


if __name__ == "__main__":
    unittest.main()
