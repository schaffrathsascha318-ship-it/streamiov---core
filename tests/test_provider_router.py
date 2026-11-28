import unittest
from unittest.mock import patch

from ai.providers.base import ModelReply
from ai.providers.local_http import (
    ProviderError,
    OllamaProvider,
    LocalOpenAICompatibleProvider,
    provider_from_env,
)
from ai.providers.router import (
    ProviderRecoveryError,
    ProviderRouter,
    TaskScopedProvider,
    provider_for_role,
)


class FakeProvider:
    def __init__(self, name, *, reply=None, error=None, ready=True):
        self.name = name
        self.reply = reply or ModelReply("ok", name, "test-model")
        self.error = error
        self.ready = ready
        self.calls = 0

    def check_ready(self):
        return {
            "provider": self.name,
            "model": "test-model",
            "reachable": self.ready,
            "model_available": self.ready,
            "ready": self.ready,
            "detail": "ready" if self.ready else "offline",
        }

    def generate(self, *, system, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


class ProviderRouterTests(unittest.TestCase):
    def test_falls_back_after_quota_error_and_returns_real_provider_reply(self):
        cloud = FakeProvider("cloudflare", error=ProviderError("daily AI quota exhausted (429)"))
        local = FakeProvider("ollama", reply=ModelReply("local result", "ollama", "qwen2.5-coder:7b"))
        router = ProviderRouter([("cloudflare", cloud), ("ollama", local)])

        reply = router.generate(system="system", messages=[{"role": "user", "content": "hello"}])

        self.assertEqual(reply.content, "local result")
        self.assertEqual(reply.provider, "ollama")
        self.assertEqual(cloud.calls, 1)
        self.assertEqual(local.calls, 1)

    def test_provider_order_is_preserved_and_stops_after_success(self):
        first = FakeProvider("local-primary")
        second = FakeProvider("cloud-secondary")
        router = ProviderRouter([("local-primary", first), ("cloud-secondary", second)])

        self.assertEqual(router.generate(system="", messages=[]).provider, "local-primary")
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 0)

    def test_health_report_identifies_first_ready_provider(self):
        offline = FakeProvider("ollama", ready=False)
        online = FakeProvider("self-hosted", ready=True)
        report = ProviderRouter([("ollama", offline), ("self-hosted", online)]).check_ready()

        self.assertTrue(report["ready"])
        self.assertEqual(report["active_provider"], "self-hosted")
        self.assertFalse(report["providers"][0]["ready"])
        self.assertTrue(report["providers"][1]["ready"])

    def test_all_provider_failures_are_reported_without_claiming_success(self):
        router = ProviderRouter([
            ("ollama", FakeProvider("ollama", error=ProviderError("connection refused"))),
            ("cloudflare", FakeProvider("cloudflare", error=ProviderError("quota 429"))),
        ])
        with self.assertRaisesRegex(ProviderError, "All configured.*ollama.*cloudflare"):
            router.generate(system="", messages=[])

    def test_rejects_empty_or_duplicate_provider_configuration(self):
        with self.assertRaises(ProviderError):
            ProviderRouter([])
        provider = FakeProvider("same")
        with self.assertRaisesRegex(ProviderError, "only appear once"):
            ProviderRouter([("same", provider), ("same", provider)])

    def test_environment_can_configure_local_first_and_cloudflare_second(self):
        token = "streamiov-test-token-with-more-than-32-characters"
        with patch.dict("os.environ", {
            "STREAMIOV_MODEL_PROVIDERS": "ollama,cloudflare-workers-ai",
            "STREAMIOV_OLLAMA_MODEL": "qwen2.5-coder:7b",
            "STREAMIOV_OLLAMA_URL": "http://127.0.0.1:11434",
            "STREAMIOV_MODEL_URL": "https://streamiov-ai.example.workers.dev",
            "STREAMIOV_AI_WORKER_TOKEN": token,
        }, clear=True):
            router = provider_from_env()

        self.assertIsInstance(router, ProviderRouter)
        self.assertEqual([name for name, _ in router.providers], ["ollama", "cloudflare-workers-ai"])
        self.assertIsInstance(router.providers[0][1], OllamaProvider)
        self.assertEqual(router.providers[0][1].model, "qwen2.5-coder:7b")

    def test_local_providers_request_json_constrained_model_output(self):
        captured = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"message":{"content":"{}"}}'

        def fake_urlopen(request, timeout):
            import json
            captured.append((request.full_url, json.loads(request.data.decode("utf-8")), timeout))
            return Response()

        with patch("ai.providers.local_http.urlopen", side_effect=fake_urlopen):
            OllamaProvider("qwen2.5-coder:1.5b").generate(system="Return JSON.", messages=[])
        self.assertEqual(captured[0][1]["format"], "json")

        def fake_openai_urlopen(request, timeout):
            import json
            captured.append((request.full_url, json.loads(request.data.decode("utf-8")), timeout))
            class OpenAIResponse(Response):
                def read(self):
                    return b'{"choices":[{"message":{"content":"{}"}}]}'
            return OpenAIResponse()

        with patch("ai.providers.local_http.urlopen", side_effect=fake_openai_urlopen):
            LocalOpenAICompatibleProvider("local-model").generate(system="Return JSON.", messages=[])
        self.assertEqual(captured[1][1]["response_format"], {"type": "json_object"})

    def test_environment_router_rejects_unknown_provider(self):
        with patch.dict("os.environ", {"STREAMIOV_MODEL_PROVIDERS": "ollama,unknown"}, clear=True):
            with self.assertRaisesRegex(ProviderError, "Unsupported provider"):
                provider_from_env()

    def test_environment_without_provider_list_preserves_legacy_selection(self):
        with patch.dict("os.environ", {
            "STREAMIOV_MODEL_PROVIDER": "ollama",
            "STREAMIOV_MODEL": "existing-model",
            "STREAMIOV_MODEL_URL": "http://127.0.0.1:11434",
        }, clear=True):
            provider = provider_from_env()
        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.model, "existing-model")

    def test_quota_failure_sets_cooldown_and_router_keeps_using_fallback(self):
        class QuotaError(ProviderError):
            failure_class = "quota"

        cloud = FakeProvider("cloudflare-workers-ai", error=QuotaError("daily_ai_limit_reached (429)"))
        local = FakeProvider("ollama", reply=ModelReply("fallback", "ollama", "small"))
        router = ProviderRouter([("cloudflare-workers-ai", cloud), ("ollama", local)])

        self.assertEqual(router.generate(system="", messages=[]).content, "fallback")
        self.assertEqual(router.generate(system="", messages=[]).content, "fallback")
        self.assertEqual(cloud.calls, 1)
        self.assertEqual(local.calls, 2)
        self.assertGreater(router._cooldown_remaining("cloudflare-workers-ai"), 0)

    def test_all_quota_providers_in_cooldown_raise_structured_recovery_error(self):
        class QuotaError(ProviderError):
            failure_class = "quota"

        router = ProviderRouter([("cloudflare-workers-ai", FakeProvider("cloudflare-workers-ai", error=QuotaError("daily_ai_limit_reached")))])
        with self.assertRaises(ProviderRecoveryError):
            router.generate(system="", messages=[])
        with self.assertRaises(ProviderRecoveryError) as caught:
            router.generate(system="", messages=[])
        self.assertEqual(caught.exception.failure_class, "provider_quota_all")
        self.assertIn("failure_class=provider_quota_all", str(caught.exception))

    def test_provider_for_role_restricts_loopback_models_for_complex_tasks(self):
        cloud = FakeProvider("cloudflare-workers-ai")
        local = FakeProvider("ollama")
        router = ProviderRouter([("cloudflare-workers-ai", cloud), ("ollama", local)])

        complex_provider = provider_for_role(router, "code")
        self.assertIsInstance(complex_provider, TaskScopedProvider)
        self.assertEqual(complex_provider.allowed_providers, ("cloudflare-workers-ai",))
        self.assertIsNone(complex_provider.max_actions)
        simple_provider = provider_for_role(router, "research")
        self.assertEqual(simple_provider.allowed_providers, ("cloudflare-workers-ai", "ollama"))
        self.assertEqual(simple_provider.max_actions, 12)
        self.assertEqual(
            provider_for_role(router, "LOCAL_RECOVERY_ELIGIBLE").max_actions, 12,
        )
        recovery = provider_for_role(complex_provider, "LOCAL_RECOVERY_ELIGIBLE")
        self.assertIsInstance(recovery, TaskScopedProvider)
        self.assertEqual(recovery.allowed_providers, ("cloudflare-workers-ai", "ollama"))
        self.assertEqual(recovery.max_actions, 12)


if __name__ == "__main__":
    unittest.main()
