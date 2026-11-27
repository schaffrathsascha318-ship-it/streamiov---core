"""OAuth2 provider adapters for authenticated Core platform connections."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config" / "platforms"
CONFIG_DIR_ENV = "STREAMIOV_PLATFORM_CONFIG_DIR"
ENVIRONMENT_ENV = "STREAMIOV_PLATFORM_ENV"
STATE_TTL_SECONDS = 600
MAX_RESPONSE_BYTES = 65536
PLATFORMS = frozenset({"tiktok", "twitch"})


class OAuthProviderError(ValueError):
    def __init__(self, code: str, detail: str = "", *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.detail = detail[:200]
        self.retryable = retryable


class _NoCredentialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _read_config(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OAuthProviderError("oauth_config_unavailable") from exc
    if not isinstance(payload, dict):
        raise OAuthProviderError("oauth_config_invalid")
    return payload


def _validate_endpoint(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OAuthProviderError(f"{name}_missing")
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname or ""
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError
        if parsed.scheme not in {"https", "http"}:
            raise ValueError
        if parsed.scheme == "http":
            try:
                if not ipaddress.ip_address(host).is_loopback:
                    raise ValueError
            except ValueError as exc:
                raise OAuthProviderError(f"{name}_must_use_https") from exc
    except ValueError as exc:
        raise OAuthProviderError(f"{name}_invalid") from exc
    return value


def _validate_redirect_uri(value: Any, environment: str) -> str:
    if not isinstance(value, str) or not value:
        raise OAuthProviderError("redirect_uri_missing")
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname or ""
        if not parsed.scheme or not host or parsed.username or parsed.password or parsed.fragment:
            raise ValueError
        if environment == "production":
            if parsed.scheme != "https":
                raise OAuthProviderError("production_redirect_requires_https")
        elif environment == "sandbox":
            if parsed.scheme != "http" or not ipaddress.ip_address(host).is_loopback or not parsed.port:
                raise OAuthProviderError("sandbox_redirect_requires_loopback_http")
        else:
            raise OAuthProviderError("oauth_environment_invalid")
    except OAuthProviderError:
        raise
    except ValueError as exc:
        raise OAuthProviderError("redirect_uri_invalid") from exc
    return value


def _parse_scopes(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = [item.strip() for item in value.replace(",", " ").split()]
    elif isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        parts = [item.strip() for item in value]
    else:
        raise OAuthProviderError("oauth_scopes_invalid")
    scopes = list(dict.fromkeys(item for item in parts if item))
    if any(len(item) > 128 for item in scopes) or len(scopes) > 32:
        raise OAuthProviderError("oauth_scopes_invalid")
    return scopes


@dataclass(frozen=True)
class OAuthProviderConfig:
    platform: str
    environment: str
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    authorization_endpoint: str
    token_endpoint: str
    revoke_endpoint: str
    scopes: tuple[str, ...]
    identity_endpoint: str | None
    identity_fields: str | None
    client_id_param: str
    scope_separator: str
    pkce: bool
    pkce_challenge_encoding: str
    revoke_requires_secret: bool
    rotate_refresh_token: bool

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    @property
    def missing(self) -> tuple[str, ...]:
        missing = []
        if not self.client_id:
            missing.append("client_id")
        if not self.client_secret:
            missing.append("client_secret")
        if not self.redirect_uri:
            missing.append("redirect_uri")
        return tuple(missing)

    @classmethod
    def from_environment(cls, platform: str, *, config_dir: str | Path | None = None,
                         environment: str | None = None) -> "OAuthProviderConfig":
        if platform not in PLATFORMS:
            raise OAuthProviderError("platform_unsupported")
        root = Path(config_dir or os.environ.get(CONFIG_DIR_ENV) or DEFAULT_CONFIG_DIR).resolve()
        if environment is None:
            environment = os.environ.get(ENVIRONMENT_ENV, "sandbox").strip().lower()
        if environment not in {"sandbox", "production"}:
            raise OAuthProviderError("oauth_environment_invalid")
        config = _read_config(root / platform / "oauth.json")
        if not config.get("enabled"):
            raise OAuthProviderError("platform_disabled")
        if platform == "tiktok":
            environments = config.get("environments")
            if not isinstance(environments, dict) or environment not in environments:
                raise OAuthProviderError("oauth_environment_unavailable")
            details = environments[environment]
            if not isinstance(details, dict):
                raise OAuthProviderError("oauth_config_invalid")
            client_id_key = details.get("client_key_env", "")
            client_id_env = os.environ.get(str(client_id_key), "").strip() if client_id_key else ""
            client_secret_key = details.get("client_secret_env", "")
            client_secret = (os.environ.get(str(client_secret_key), "").strip()
                             if client_secret_key else "")
            redirect_key = details.get("redirect_uri_env", "")
            redirect_uri = os.environ.get(str(redirect_key), "").strip() if redirect_key else ""
            scopes = tuple(_parse_scopes(details.get("allowed_scopes", [])))
        else:
            client_id_key = config.get("client_id_env", "")
            client_id_env = os.environ.get(str(client_id_key), "").strip() if client_id_key else ""
            client_secret_key = config.get("client_secret_env", "")
            client_secret = (os.environ.get(str(client_secret_key), "").strip()
                             if client_secret_key else "")
            redirect_key = config.get("redirect_uri_env", "")
            redirect_uri = os.environ.get(str(redirect_key), "").strip() if redirect_key else ""
            scopes = tuple(_parse_scopes(config.get("required_scopes", [])))
        authorization = _validate_endpoint(config.get("authorization_endpoint"), "authorization_endpoint")
        token = _validate_endpoint(config.get("token_endpoint"), "token_endpoint")
        revoke = _validate_endpoint(config.get("revoke_endpoint"), "revoke_endpoint")
        identity = config.get("identity_endpoint")
        if identity:
            identity = _validate_endpoint(identity, "identity_endpoint")
        if redirect_uri:
            redirect_uri = _validate_redirect_uri(redirect_uri, environment)
        pkce = config.get("pkce_method") == "S256"
        challenge_encoding = str(config.get("pkce_challenge_encoding") or "base64url")
        if challenge_encoding not in {"base64url", "hex"}:
            raise OAuthProviderError("pkce_encoding_invalid")
        return cls(
            platform=platform,
            environment=environment,
            client_id=client_id_env or None,
            client_secret=client_secret or None,
            redirect_uri=redirect_uri or None,
            authorization_endpoint=authorization,
            token_endpoint=token,
            revoke_endpoint=revoke,
            scopes=scopes,
            identity_endpoint=identity,
            identity_fields=str(config.get("identity_fields") or "") or None,
            client_id_param=str(config.get("client_id_param") or "client_id"),
            scope_separator=str(config.get("scope_separator") or " "),
            pkce=pkce,
            pkce_challenge_encoding=challenge_encoding,
            revoke_requires_secret=bool(config.get("revoke_requires_secret", False)),
            rotate_refresh_token=bool(config.get("rotate_refresh_token", False)),
        )


def platform_config_status(platform: str, *, config_dir: str | Path | None = None) -> dict[str, Any]:
    try:
        config = OAuthProviderConfig.from_environment(platform, config_dir=config_dir)
    except OAuthProviderError as exc:
        return {"platform": platform, "configured": False, "error": exc.code,
                "missing": (), "scopes": (), "environment": None}
    return {
        "platform": platform,
        "configured": config.configured,
        "missing": list(config.missing),
        "scopes": list(config.scopes),
        "environment": config.environment,
        "redirect_uri": config.redirect_uri,
        "pkce": config.pkce,
    }


class OAuthProvider:
    def __init__(self, config: OAuthProviderConfig, *, opener: Callable | None = None):
        if not config.configured:
            raise OAuthProviderError("oauth_not_configured")
        self.config = config
        self._opener = opener or urllib.request.build_opener(_NoCredentialRedirectHandler())

    def create_authorization(self) -> dict[str, Any]:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48) if self.config.pkce else None
        params: dict[str, str] = {
            self.config.client_id_param: self.config.client_id or "",
            "redirect_uri": self.config.redirect_uri or "",
            "response_type": "code",
            "scope": self.config.scope_separator.join(self.config.scopes),
            "state": state,
        }
        if self.config.pkce and verifier:
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            if self.config.pkce_challenge_encoding == "hex":
                challenge = digest.hex()
            else:
                challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"
        if self.config.platform == "twitch":
            params["force_verify"] = "false"
        separator = "&" if "?" in self.config.authorization_endpoint else "?"
        return {
            "url": self.config.authorization_endpoint + separator + urllib.parse.urlencode(params),
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": self.config.redirect_uri,
            "scopes": list(self.config.scopes),
            "expires_in": STATE_TTL_SECONDS,
        }

    def exchange_code(self, code: str, *, code_verifier: str | None) -> dict[str, Any]:
        if not isinstance(code, str) or not code or len(code) > 2048:
            raise OAuthProviderError("authorization_code_invalid")
        fields: dict[str, str] = {
            self.config.client_id_param: self.config.client_id or "",
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.config.redirect_uri or "",
        }
        if self.config.client_secret:
            fields["client_secret"] = self.config.client_secret
        if self.config.pkce:
            if not code_verifier:
                raise OAuthProviderError("pkce_verifier_missing")
            fields["code_verifier"] = code_verifier
        data = self._post(self.config.token_endpoint, fields)
        tokens = self._normalize_tokens(data)
        self._require_scopes(tokens["scopes"])
        identity = self._fetch_identity(tokens["access_token"])
        tokens["account_id"] = identity["account_id"] or tokens.get("open_id") or ""
        tokens["account_name"] = identity["account_name"]
        if not tokens["account_id"]:
            raise OAuthProviderError("provider_identity_unavailable")
        if identity["scopes"]:
            self._require_scopes(identity["scopes"])
        return tokens

    def refresh(self, refresh_token: str, *, scopes: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(refresh_token, str) or not refresh_token:
            raise OAuthProviderError("refresh_token_unavailable")
        fields: dict[str, str] = {
            self.config.client_id_param: self.config.client_id or "",
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if self.config.client_secret:
            fields["client_secret"] = self.config.client_secret
        data = self._post(self.config.token_endpoint, fields)
        tokens = self._normalize_tokens(data, fallback_refresh=refresh_token)
        if self.config.rotate_refresh_token and not data.get("refresh_token"):
            raise OAuthProviderError("refresh_token_rotation_missing")
        expected = scopes or list(self.config.scopes)
        self._require_scopes(tokens["scopes"], required=expected)
        return tokens

    def revoke(self, token: str) -> None:
        if not isinstance(token, str) or not token:
            raise OAuthProviderError("token_unavailable")
        fields = {self.config.client_id_param: self.config.client_id or "", "token": token}
        if self.config.client_secret and self.config.revoke_requires_secret:
            fields["client_secret"] = self.config.client_secret
        self._post(self.config.revoke_endpoint, fields)

    def _require_scopes(self, granted: list[str], *, required: list[str] | None = None) -> None:
        expected = list(self.config.scopes if required is None else required)
        missing = [item for item in expected if item not in granted]
        if missing:
            raise OAuthProviderError("required_scope_not_granted")

    def _normalize_tokens(self, data: Any, *, fallback_refresh: str | None = None) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise OAuthProviderError("oauth_provider_invalid_response")
        access = data.get("access_token")
        if not isinstance(access, str) or not access or len(access) > 4096:
            raise OAuthProviderError("oauth_provider_invalid_response")
        try:
            expires_in = int(data.get("expires_in"))
        except (TypeError, ValueError) as exc:
            raise OAuthProviderError("oauth_provider_invalid_response") from exc
        if expires_in <= 0 or expires_in > 30 * 24 * 60 * 60:
            raise OAuthProviderError("oauth_provider_invalid_response")
        refresh = data.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            refresh = fallback_refresh
        if refresh and len(refresh) > 4096:
            raise OAuthProviderError("oauth_provider_invalid_response")
        raw_scopes = data.get("scope", data.get("scopes"))
        scopes = _parse_scopes(raw_scopes) if raw_scopes is not None else []
        from datetime import datetime, timedelta, timezone
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": expires_at,
            "scopes": scopes,
            "open_id": data.get("open_id") or data.get("user_id") or None,
        }

    def _fetch_identity(self, access_token: str) -> dict[str, Any]:
        endpoint = self.config.identity_endpoint
        if not endpoint:
            return {"account_id": None, "account_name": None, "scopes": []}
        url = endpoint
        if self.config.identity_fields:
            separator = "&" if "?" in url else "?"
            url += separator + urllib.parse.urlencode({"fields": self.config.identity_fields})
        payload = self._get(url, access_token)
        if self.config.platform == "twitch":
            client_id = payload.get("client_id")
            if client_id and client_id != self.config.client_id:
                raise OAuthProviderError("provider_identity_mismatch")
            return {
                "account_id": payload.get("user_id") if isinstance(payload.get("user_id"), str) else None,
                "account_name": payload.get("login") if isinstance(payload.get("login"), str) else None,
                "scopes": _parse_scopes(payload.get("scope", [])) if payload.get("scope") is not None else [],
            }
        data = payload.get("data")
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, dict):
            return {"account_id": None, "account_name": None, "scopes": []}
        return {
            "account_id": user.get("open_id") if isinstance(user.get("open_id"), str) else None,
            "account_name": user.get("display_name") if isinstance(user.get("display_name"), str) else None,
            "scopes": [],
        }

    def _post(self, url: str, fields: dict[str, str]) -> dict[str, Any]:
        body = urllib.parse.urlencode(fields).encode("ascii")
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Cache-Control": "no-store",
        })
        return self._request_json(request)

    def _get(self, url: str, access_token: str) -> dict[str, Any]:
        request = urllib.request.Request(url, method="GET", headers={
            "Authorization": "Bearer " + access_token,
            "Accept": "application/json",
            "Cache-Control": "no-store",
        })
        return self._request_json(request)

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            opener = self._opener
            if hasattr(opener, "open"):
                response_context = opener.open(request, timeout=8)
            else:
                response_context = opener(request, timeout=8)
            with response_context as response:
                if getattr(response, "geturl", lambda: request.full_url)() != request.full_url:
                    raise OAuthProviderError("oauth_provider_redirect_rejected")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read(4096).decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                data = {}
            code = data.get("error") if isinstance(data, dict) else None
            if isinstance(code, str) and code in {
                "invalid_grant", "invalid_client", "unauthorized_client",
                "access_denied", "invalid_scope",
            }:
                raise OAuthProviderError(code)
            if 300 <= exc.code < 400:
                raise OAuthProviderError("oauth_provider_redirect_rejected")
            if exc.code in {400, 401, 403}:
                raise OAuthProviderError("oauth_provider_rejected")
            raise OAuthProviderError("oauth_provider_unavailable", retryable=True)
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise OAuthProviderError("oauth_provider_unavailable", retryable=True) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OAuthProviderError("oauth_provider_invalid_response")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OAuthProviderError("oauth_provider_invalid_response") from exc
        if not isinstance(payload, dict):
            raise OAuthProviderError("oauth_provider_invalid_response")
        return payload
