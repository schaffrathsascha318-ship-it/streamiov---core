"""Local encrypted token storage for verified platform connections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any


class TokenCryptoError(ValueError):
    pass


class TokenCrypto:
    VERSION = 1
    ALGORITHM = "pbkdf2-sha256+sha256-counter+hmac-sha256"
    ITERATIONS = 200_000
    KEY_ENV = "STREAMIOV_TOKEN_KEY"
    KEY_FILE = "oauth-token.key"
    PREVIOUS_KEY_ENV = "STREAMIOV_TOKEN_KEY_PREVIOUS"
    PREVIOUS_KEY_FILE = "oauth-token.previous.key"
    MIN_SECRET_CHARS = 16

    def __init__(
        self,
        data_dir: str | Path | None = None,
        secret: str | None = None,
        key_path: str | Path | None = None,
        previous_secret: str | None = None,
        previous_key_path: str | Path | None = None,
    ):
        root = Path(data_dir).resolve() if data_dir is not None else None
        if root is not None:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(root, 0o700)
            except OSError as exc:
                raise TokenCryptoError("Token data directory must be private to its owner.") from exc
        if secret is None:
            secret = os.environ.get(self.KEY_ENV)
        if key_path is None and root is not None:
            key_path = root / self.KEY_FILE
        self._key_path = Path(key_path).resolve() if key_path else None
        self._secret = self._prepare_secret(secret, source="environment") if secret else None
        if self._secret is None:
            self._secret = self._read_key_file(self._key_path)
        if previous_secret is None:
            previous_secret = os.environ.get(self.PREVIOUS_KEY_ENV)
        if previous_key_path is None and self._key_path is not None:
            candidate = self._key_path.parent / self.PREVIOUS_KEY_FILE
            previous_key_path = candidate if candidate.is_file() else None
        self._previous_secret = None
        if previous_secret:
            try:
                self._previous_secret = self._prepare_secret(previous_secret, source="previous environment")
            except TokenCryptoError:
                self._previous_secret = None
        if self._previous_secret is None and previous_key_path is not None:
            path = Path(previous_key_path).resolve()
            if path.is_file() and not path.is_symlink():
                try:
                    self._previous_secret = self._read_key_file(path)
                except TokenCryptoError:
                    self._previous_secret = None

    @classmethod
    def _prepare_secret(cls, secret: str, *, source: str) -> bytes:
        if not isinstance(secret, str) or len(secret.strip()) < cls.MIN_SECRET_CHARS:
            raise TokenCryptoError(f"Token key from {source} is too short.")
        value = secret.strip().encode("utf-8")
        return value

    @classmethod
    def _read_key_file(cls, path: Path | None) -> bytes:
        if path is None or not path.is_file() or path.is_symlink():
            raise TokenCryptoError(
                "Set STREAMIOV_TOKEN_KEY or provide a readable key file before storing platform tokens."
            )
        try:
            os.chmod(path, 0o600)
        except OSError as exc:
            raise TokenCryptoError("Token key file must be owned by the host process.") from exc
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise TokenCryptoError("Token key file is not readable.") from exc
        return cls._prepare_secret(value, source="key file")

    def _load_secret(self) -> bytes:
        if self._secret is None:
            raise TokenCryptoError("No token encryption key is available.")
        return self._secret

    @staticmethod
    def _key_id(secret: bytes) -> str:
        return hashlib.sha256(secret).hexdigest()[:12]

    @staticmethod
    def _encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii")

    @staticmethod
    def _decode(data: str) -> bytes:
        return base64.urlsafe_b64decode(data.encode("ascii"))

    @classmethod
    def _canonical(cls, header: dict[str, Any]) -> bytes:
        return json.dumps(
            header, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    @classmethod
    def _derive(cls, secret: bytes, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", secret, salt, cls.ITERATIONS, 32)

    @staticmethod
    def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
        parts: list[bytes] = []
        counter = 0
        while sum(len(part) for part in parts) < length:
            parts.append(
                hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
            )
            counter += 1
        return b"".join(parts)[:length]

    def encrypt(self, plaintext: str) -> str:
        if not isinstance(plaintext, str):
            raise TokenCryptoError("plaintext must be a string")
        secret = self._load_secret()
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(16)
        key = self._derive(secret, salt)
        data = plaintext.encode("utf-8")
        stream = self._keystream(key, nonce, len(data))
        ciphertext = bytes(value ^ mask for value, mask in zip(data, stream))
        header = {
            "v": self.VERSION,
            "alg": self.ALGORITHM,
            "kid": self._key_id(secret),
            "iterations": self.ITERATIONS,
            "salt": self._encode(salt),
            "nonce": self._encode(nonce),
            "ciphertext": self._encode(ciphertext),
        }
        header["tag"] = self._encode(
            hmac.new(key, self._canonical(header), hashlib.sha256).digest()
        )
        return json.dumps(header, separators=(",", ":"), ensure_ascii=False)

    def decrypt(self, envelope: str) -> str:
        try:
            payload = json.loads(envelope)
        except (TypeError, ValueError) as exc:
            raise TokenCryptoError("token envelope is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise TokenCryptoError("token envelope must be an object")
        if payload.get("v") != self.VERSION or payload.get("alg") != self.ALGORITHM:
            raise TokenCryptoError("unsupported token envelope")
        if payload.get("iterations") != self.ITERATIONS:
            raise TokenCryptoError("unsupported token derivation parameters")
        candidates = [self._load_secret()]
        if self._previous_secret is not None:
            candidates.append(self._previous_secret)
        key_id = payload.get("kid")
        if key_id is not None:
            candidates = [
                secret for secret in candidates if hmac.compare_digest(self._key_id(secret), str(key_id))
            ]
        if not candidates:
            raise TokenCryptoError("token envelope uses an unavailable key")
        last_error: TokenCryptoError | None = None
        for secret in candidates:
            try:
                return self._decrypt_with(secret, payload)
            except TokenCryptoError as exc:
                last_error = exc
        raise last_error or TokenCryptoError("token envelope failed authentication")

    def _decrypt_with(self, secret: bytes, payload: dict[str, Any]) -> str:
        try:
            salt = self._decode(payload["salt"])
            nonce = self._decode(payload["nonce"])
            ciphertext = self._decode(payload["ciphertext"])
            tag = self._decode(payload["tag"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TokenCryptoError("token envelope is incomplete") from exc
        header = {key: value for key, value in payload.items() if key != "tag"}
        key = self._derive(secret, salt)
        expected = hmac.new(key, self._canonical(header), hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise TokenCryptoError("token envelope failed authentication")
        stream = self._keystream(key, nonce, len(ciphertext))
        plaintext = bytes(value ^ mask for value, mask in zip(ciphertext, stream))
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TokenCryptoError("token plaintext is invalid") from exc
