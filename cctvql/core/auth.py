"""
cctvQL Multi-Tenant Authentication
------------------------------------
JWT-based authentication and user management.

Enabled by setting ``CCTVQL_MULTI_TENANT=1``.  When disabled (default), the
API works exactly as before — no breaking changes.

Implementation uses Python stdlib only (hashlib, hmac, json, base64) — no
third-party auth libraries required.

Password storage
----------------
Passwords are hashed with PBKDF2-HMAC-SHA256, 600 000 iterations, 16-byte
random salt, stored as ``pbkdf2:<hex-salt>:<hex-digest>``.

Token format
------------
Standard three-part JWT (Header.Payload.Signature) where the signature is
HMAC-SHA256 over ``header.payload`` using the server's secret key.

The secret key is read from ``CCTVQL_SECRET_KEY``.  If not set, a random key
is generated at startup (tokens are invalidated on restart in that case).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

_TOKEN_EXPIRE_HOURS = int(os.environ.get("CCTVQL_TOKEN_EXPIRE_HOURS", "24"))

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
_VALID_ROLES = {ROLE_ADMIN, ROLE_VIEWER}

_JWT_HEADER_B64 = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()


@dataclass
class User:
    """A cctvQL user account."""

    id: str
    username: str
    password_hash: str
    role: str = ROLE_VIEWER
    camera_groups: list[str] = field(default_factory=list)
    """Camera names this user can access.  Empty list means all cameras."""
    created_at: datetime = field(default_factory=datetime.utcnow)
    active: bool = True

    def can_see_camera(self, camera_name: str) -> bool:
        """Return True if this user has access to the given camera."""
        if self.role == ROLE_ADMIN:
            return True
        if not self.camera_groups:
            return True  # viewer with no restrictions sees everything
        return camera_name.lower() in [c.lower() for c in self.camera_groups]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "camera_groups": self.camera_groups,
            "created_at": self.created_at.isoformat(),
            "active": self.active,
        }


# ---------------------------------------------------------------------------
# Auth manager
# ---------------------------------------------------------------------------


class AuthManager:
    """
    Handles password hashing, JWT generation, and JWT verification.

    Args:
        secret_key: HMAC key used to sign tokens.  If omitted, read from
                    ``CCTVQL_SECRET_KEY`` env var or generate a random one.
    """

    def __init__(self, secret_key: str | None = None) -> None:
        key = secret_key or os.environ.get("CCTVQL_SECRET_KEY") or secrets.token_hex(32)
        self._secret: bytes = key.encode()

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def hash_password(self, password: str) -> str:
        """Return a salted PBKDF2-HMAC-SHA256 hash of *password*."""
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
        return f"pbkdf2:{salt}:{digest.hex()}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        """Verify *password* against a stored PBKDF2 hash."""
        parts = stored_hash.split(":")
        if len(parts) != 3 or parts[0] != "pbkdf2":
            return False
        _, salt, hex_digest = parts
        attempt = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
        return hmac.compare_digest(attempt.hex(), hex_digest)

    # ------------------------------------------------------------------
    # JWT helpers
    # ------------------------------------------------------------------

    def create_token(self, user: User) -> str:
        """Return a signed JWT for *user*."""
        payload = {
            "sub": user.id,
            "username": user.username,
            "role": user.role,
            "camera_groups": user.camera_groups,
            "exp": int(time.time()) + _TOKEN_EXPIRE_HOURS * 3600,
            "iat": int(time.time()),
        }
        body_b64 = (
            base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
            .rstrip(b"=")
            .decode()
        )
        signing_input = f"{_JWT_HEADER_B64}.{body_b64}".encode()
        sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{_JWT_HEADER_B64}.{body_b64}.{sig_b64}"

    def verify_token(self, token: str) -> dict | None:
        """
        Verify *token* and return the decoded payload, or ``None`` if invalid
        (bad signature, expired, or malformed).
        """
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{body_b64}".encode()
        expected_sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        try:
            provided_sig = base64.urlsafe_b64decode(sig_b64 + "==")
        except Exception:
            return None
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None

        try:
            payload = json.loads(base64.urlsafe_b64decode(body_b64 + "=="))
        except Exception:
            return None

        if payload.get("exp", 0) < time.time():
            logger.debug("JWT expired for user %s", payload.get("username"))
            return None
        return payload

    # ------------------------------------------------------------------
    # User factory
    # ------------------------------------------------------------------

    def make_user(
        self,
        username: str,
        password: str,
        role: str = ROLE_VIEWER,
        camera_groups: list[str] | None = None,
    ) -> User:
        """Create a new User (not yet persisted)."""
        return User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=self.hash_password(password),
            role=role,
            camera_groups=camera_groups or [],
        )
