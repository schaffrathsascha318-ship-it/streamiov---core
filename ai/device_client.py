"""Secure desktop client for the scoped OpenCode Core device API.

Credentials are stored only in a supported OS credential vault. This client
never falls back to plaintext files, environment variables, or browser storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform as platform_module
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class DeviceClientError(RuntimeError):
    """Safe-to-display device client error."""


def normalize_server_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise DeviceClientError("Ungültige Core-Server-Adresse.")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise DeviceClientError("Die Server-Adresse muss mit https:// beginnen.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DeviceClientError("Die Server-Adresse darf keine Zugangsdaten oder Zusatzparameter enthalten.")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise DeviceClientError("Unverschlüsseltes HTTP ist nur für lokale Entwicklung erlaubt.")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise DeviceClientError(
            "Sichere Gerätespeicherung fehlt. Installiere das optionale Paket "
            "mit: pip install 'opencode-core[device]'"
        ) from exc
    backend = keyring.get_keyring()
    backend_name = f"{type(backend).__module__}.{type(backend).__name__}".lower()
    supported = (
        "windows.winvaultkeyring",
        "macos.keyring",
        "secretservice.keyring",
    )
    if not any(name in backend_name for name in supported):
        raise DeviceClientError(
            "Kein unterstützter Betriebssystem-Tresor aktiv. "
            "Erforderlich sind Windows Credential Vault, macOS Keychain "
            "oder Linux Secret Service. Es wird kein unsicherer Fallback verwendet."
        )
    try:
        if float(backend.priority) <= 0:
            raise DeviceClientError("Der Betriebssystem-Tresor ist nicht verfügbar.")
    except (AttributeError, TypeError, ValueError) as exc:
        raise DeviceClientError("Der Betriebssystem-Tresor konnte nicht verifiziert werden.") from exc
    return backend


def _service(server: str) -> str:
    digest = hashlib.sha256(server.encode("utf-8")).hexdigest()
    return f"opencode-core-device:{digest}"


class _NoRedirect(HTTPRedirectHandler):
    """Never forward a device bearer token through an HTTP redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect())


def _request(server: str, path: str, *, method: str = "GET", payload=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(server + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=12) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise DeviceClientError("Die Serverantwort ist unerwartet groß.")
            result = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        # Do not print response bodies: they may contain server-side details.
        if exc.code == 401:
            raise DeviceClientError("Geräteanmeldung ungültig oder abgelaufen. Gerät neu koppeln.") from exc
        if exc.code == 429:
            raise DeviceClientError("Zu viele Versuche. Bitte später erneut versuchen.") from exc
        raise DeviceClientError(f"Core-Server antwortet mit HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DeviceClientError("Core-Server nicht erreichbar. Verbindung wird beim nächsten Aufruf erneut versucht.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeviceClientError("Ungültige Antwort vom Core-Server.") from exc
    if not isinstance(result, dict):
        raise DeviceClientError("Ungültige Antwort vom Core-Server.")
    return result


def enroll(server: str, code: str, name: str, os_name: str | None = None) -> dict:
    server = normalize_server_url(server)
    vault = _keyring()  # Fail closed before consuming the single-use pairing code.
    selected_platform = os_name or detect_platform()
    result = _request(server, "/api/v1/devices/enroll", method="POST", payload={
        "pairing_code": code,
        "name": name,
        "platform": selected_platform,
    })
    token = result.get("device_token")
    device = result.get("device")
    if not isinstance(token, str) or not isinstance(device, dict):
        raise DeviceClientError("Der Server hat keine gültigen Gerätezugangsdaten geliefert.")
    try:
        vault.set_password(_service(server), "device-token", token)
    except Exception as exc:
        raise DeviceClientError(
            "Der Betriebssystem-Tresor konnte das Gerätetoken nicht speichern. "
            "Widerrufe dieses Gerät anschließend in der Kontoverwaltung."
        ) from exc
    return device


def detect_platform() -> str:
    system = sys.platform
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    if system.startswith("linux"):
        return "linux"
    raise DeviceClientError("Dieses Betriebssystem wird von diesem Desktop-Client nicht erkannt.")


def status(server: str) -> dict:
    server = normalize_server_url(server)
    vault = _keyring()
    token = vault.get_password(_service(server), "device-token")
    if not token:
        raise DeviceClientError("Für diesen Core-Server ist kein Gerät gekoppelt.")
    return _request(server, "/api/v1/device/status", token=token)


def forget(server: str) -> None:
    server = normalize_server_url(server)
    vault = _keyring()
    vault.delete_password(_service(server), "device-token")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opencode-core-device", description="OpenCode Core Geräteverbindung")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("enroll", help="Gerät mit einem einmaligen Kopplungscode anmelden")
    pair.add_argument("--server", required=True)
    pair.add_argument("--code", required=True)
    pair.add_argument("--name", required=True)
    pair.add_argument("--platform", choices=("windows", "linux", "macos", "chromeos", "android", "ios"))
    check = commands.add_parser("status", help="Verbindung und Gerätestatus erneut prüfen")
    check.add_argument("--server", required=True)
    remove = commands.add_parser("forget", help="Lokales Gerätetoken aus dem OS-Tresor entfernen")
    remove.add_argument("--server", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "enroll":
            device = enroll(args.server, args.code, args.name, args.platform)
            print(json.dumps({"status": "paired", "device": device}, ensure_ascii=False, indent=2))
        elif args.command == "status":
            result = status(args.server)
            print(json.dumps({
                "status": "connected",
                "service": result.get("service"),
                "version": result.get("version"),
                "device": result.get("device"),
                "task_api_ready": bool(result.get("task_api_ready")),
                "workspace_access": bool(result.get("workspace_access")),
            }, ensure_ascii=False, indent=2))
        else:
            forget(args.server)
            print(json.dumps({"status": "local_credentials_removed"}, ensure_ascii=False))
        return 0
    except DeviceClientError as exc:
        print(f"opencode-core-device: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
