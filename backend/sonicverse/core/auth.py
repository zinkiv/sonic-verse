"""Password hashing and HMAC session tokens (same shape as navi-dock)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from functools import lru_cache

import bcrypt

from sonicverse.core.config import get_settings

logger = logging.getLogger(__name__)

_SECRET_FILE = ".auth_secret"


class AuthError(Exception):
    """User-facing auth failure."""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    role: str
    disabled: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@lru_cache
def get_auth_secret() -> bytes:
    settings = get_settings()
    configured = (settings.auth_secret or "").strip()
    if configured:
        return configured.encode("utf-8")

    path = settings.data_path / _SECRET_FILE
    try:
        if path.is_file():
            stored = path.read_text(encoding="utf-8").strip()
            if stored:
                return stored.encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_hex(32)
        path.write_text(generated, encoding="utf-8")
        return generated.encode("utf-8")
    except OSError:
        logger.warning("Could not persist auth secret at %s; using a process secret", path)
        return secrets.token_hex(32).encode("utf-8")


def issue_token(user: AuthUser) -> str:
    payload = json.dumps(
        {"uid": user.id, "name": user.username, "role": user.role, "exp": 0},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64url(payload)
    sig = hmac.new(get_auth_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64url(sig)}"


def parse_token(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 2:
        return None
    encoded, sig = parts
    expected = _b64url(
        hmac.new(get_auth_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        claims = json.loads(_b64url_decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(claims, dict) or not claims.get("uid"):
        return None
    return claims
