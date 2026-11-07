import unittest

from ai.providers.base import ModelReply
from ai.providers.local_http import ProviderError
from ai.providers.router import FallbackModelProvider


class FakeProvider:
    def __init__(self, name, *, error=None, ready=True):
        self.name = name
        self.error = error
        self.ready = ready
        self.calls = 0

    def generate(self, *, system, messages):
        self.calls += 1
        if self.error:
            raise ProviderError(self.error)
        return ModelReply("ok", self.name, "test-model")

    def check_ready(self):
        return {"provider": self.name, "ready": self.ready}


class ProviderRouterTests(unittest.TestCase):
    def test_uses_primary_when_available(self):
        primary = FakeProvider("primary")
        fallback = FakeProvider("fallback")
        reply = FallbackModelProvider(primary, [fallback]).generate(system="", messages=[])
        self.assertEqual(reply.provider, "primary")
        self.assertEqual(fallback.calls, 0)

    def test_uses_fallback_after_primary_quota_or_network_error(self):
        primary = FakeProvider("primary", error="HTTP 429")
        fallback = FakeProvider("fallback")
        reply = FallbackModelProvider(primary, [fallback]).generate(system="", messages=[])
        self.assertEqual(reply.provider, "fallback")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 1)

    def test_reports_failure_when_all_providers_fail(self):
        router = FallbackModelProvider(
            FakeProvider("primary", error="unavailable"),
            [FakeProvider("fallback", error="quota exhausted")],
        )
        with self.assertRaisesRegex(ProviderError, "All configured model providers failed"):
            router.generate(system="", messages=[])

    def test_readiness_is_true_when_any_provider_is_ready(self):
        status = FallbackModelProvider(
            FakeProvider("primary", ready=False),
            [FakeProvider("fallback", ready=True)],
        ).check_ready()
        self.assertTrue(status["ready"])


if __name__ == "__main__":
    unittest.main()
