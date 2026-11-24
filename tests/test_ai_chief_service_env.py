from pathlib import Path
from runpy import run_path
import unittest


ROOT = Path(__file__).resolve().parents[1]
validate_environment = run_path(
    str(ROOT / "scripts" / "ai" / "validate-chief-service-env.py")
)["validate_environment"]


class AIChiefServiceEnvironmentTests(unittest.TestCase):
    def test_valid_pinned_streamiov_worker_configuration(self):
        env = {
            "STREAMIOV_PROJECT_GOAL": "Continue verified Streamiov development.",
            "STREAMIOV_MODEL_PROVIDER": "cloudflare-workers-ai",
            "STREAMIOV_MODEL": "@cf/zai-org/glm-4.7-flash",
            "STREAMIOV_MODEL_URL": "https://streamiov-ai.example.workers.dev",
            "STREAMIOV_AI_WORKER_TOKEN": "private-token-value-that-is-long-enough",
        }
        self.assertIsNone(validate_environment(env))

    def test_rejects_empty_goal_and_placeholder_token(self):
        env = {
            "STREAMIOV_PROJECT_GOAL": " ",
            "STREAMIOV_MODEL_PROVIDER": "cloudflare-workers-ai",
            "STREAMIOV_MODEL": "@cf/zai-org/glm-4.7-flash",
            "STREAMIOV_MODEL_URL": "https://streamiov-ai.example.workers.dev",
            "STREAMIOV_AI_WORKER_TOKEN": "REPLACE_WITH_PRIVATE_AI_WORKER_TOKEN",
        }
        self.assertIn("STREAMIOV_PROJECT_GOAL", validate_environment(env))
        env["STREAMIOV_PROJECT_GOAL"] = "Continue."
        self.assertIn("placeholder", validate_environment(env))

    def test_rejects_unpinned_model_and_non_https_or_non_origin_urls(self):
        base = {
            "STREAMIOV_PROJECT_GOAL": "Continue.",
            "STREAMIOV_MODEL_PROVIDER": "cloudflare-workers-ai",
            "STREAMIOV_MODEL": "some-other-model",
            "STREAMIOV_MODEL_URL": "https://streamiov-ai.example.workers.dev",
            "STREAMIOV_AI_WORKER_TOKEN": "x" * 48,
        }
        self.assertIn("pinned", validate_environment(base))
        base["STREAMIOV_MODEL"] = "@cf/zai-org/glm-4.7-flash"
        for url in (
            "http://streamiov-ai.example.workers.dev",
            "https://streamiov-ai.example.workers.dev/path",
            "https://user:pass@streamiov-ai.example.workers.dev",
            "https://streamiov-ai.example.workers.dev?token=leak",
        ):
            with self.subTest(url=url):
                base["STREAMIOV_MODEL_URL"] = url
                self.assertIn("STREAMIOV_MODEL_URL", validate_environment(base))

    def test_accepts_local_ollama_without_cloud_credentials(self):
        env = {
            "STREAMIOV_PROJECT_GOAL": "Continue.",
            "STREAMIOV_MODEL_PROVIDER": "ollama",
            "STREAMIOV_MODEL": "qwen2.5-coder:7b",
        }
        self.assertIsNone(validate_environment(env))

    def test_rejects_unknown_provider(self):
        self.assertIn(
            "STREAMIOV_MODEL_PROVIDER",
            validate_environment({"STREAMIOV_PROJECT_GOAL": "Continue.", "STREAMIOV_MODEL_PROVIDER": "paid-api"}),
        )


if __name__ == "__main__":
    unittest.main()
