"""Tests for the secure desktop device client."""
import json
import sys
import types
import unittest
from unittest.mock import patch

from ai import device_client


class DeviceClientURLTests(unittest.TestCase):
    def test_remote_http_is_rejected_and_local_http_is_allowed(self):
        with self.assertRaises(device_client.DeviceClientError):
            device_client.normalize_server_url("http://core.example.com")
        self.assertEqual(
            device_client.normalize_server_url("http://127.0.0.1:8080/"),
            "http://127.0.0.1:8080",
        )

    def test_server_url_rejects_malformed_authority(self):
        for value in ("https://[::1", "https://core.example.com:99999"):
            with self.subTest(value=value), self.assertRaises(device_client.DeviceClientError):
                device_client.normalize_server_url(value)

    def test_server_url_rejects_embedded_credentials_and_query(self):
        for value in (
            "https://user:pass@core.example.com",
            "https://core.example.com/?token=secret",
            "https://core.example.com/#fragment",
        ):
            with self.subTest(value=value), self.assertRaises(device_client.DeviceClientError):
                device_client.normalize_server_url(value)


class DeviceClientVaultTests(unittest.TestCase):
    def test_unknown_or_insecure_keyring_backend_fails_closed(self):
        class PlaintextKeyring:
            priority = 1
        fake = types.SimpleNamespace(get_keyring=lambda: PlaintextKeyring())
        with patch.dict(sys.modules, {"keyring": fake}):
            with self.assertRaises(device_client.DeviceClientError):
                device_client._keyring()

    def test_enrollment_stores_token_only_in_supported_vault(self):
        class Keyring:
            __module__ = "keyring.backends.secretservice"
            priority = 1
            def __init__(self):
                self.saved = {}
            def set_password(self, service, username, password):
                self.saved[(service, username)] = password
        backend = SecretServiceKeyring()
        fake = types.SimpleNamespace(get_keyring=lambda: backend)
        payload = {
            "device": {"device_id": "a" * 32, "name": "Linux laptop", "platform": "linux"},
            "device_token": "t" * 48,
        }
        with patch.dict(sys.modules, {"keyring": fake}), patch.object(
            device_client, "_request", return_value=payload
        ):
            result = device_client.enroll(
                "https://core.example.com", "p" * 48, "Linux laptop", "linux"
            )
        self.assertEqual(result["platform"], "linux")
        self.assertEqual(len(backend.saved), 1)
        self.assertEqual(next(iter(backend.saved.values())), "t" * 48)

    def test_forget_deletes_only_local_vault_credential(self):
        class Keyring:
            __module__ = "keyring.backends.secretservice"
            priority = 1
            def __init__(self):
                self.deleted = []
            def delete_password(self, service, username):
                self.deleted.append((service, username))
        backend = SecretServiceKeyring()
        fake = types.SimpleNamespace(get_keyring=lambda: backend)
        with patch.dict(sys.modules, {"keyring": fake}):
            device_client.forget("https://core.example.com")
        self.assertEqual(backend.deleted, [(device_client._service("https://core.example.com"), "device-token")])

    def test_status_uses_bearer_token_from_vault(self):
        class WinVaultKeyring:
            __module__ = "keyring.backends.Windows"
            priority = 1
            def get_password(self, service, username):
                return "t" * 48
        fake = types.SimpleNamespace(get_keyring=lambda: WinVaultKeyring())
        expected = {"ok": True, "service": "streamiov-host", "task_api_ready": False}
        with patch.dict(sys.modules, {"keyring": fake}), patch.object(
            device_client, "_request", return_value=expected
        ) as request:
            result = device_client.status("https://core.example.com")
        self.assertEqual(result, expected)
        self.assertEqual(request.call_args.kwargs["token"], "t" * 48)


if __name__ == "__main__":
    unittest.main()
