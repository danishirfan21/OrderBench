"""Password hashing and bearer tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta

import jwt

from app.errors import AuthenticationError

_ALGORITHM = "HS256"


def hash_password(password: str, cost_exp: int = 14) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**cost_exp, r=8, p=1, maxmem=2**27, dklen=32
    )
    return f"scrypt${cost_exp}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, cost, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=2 ** int(cost),
            r=8,
            p=1,
            maxmem=2**27,
            dklen=32,
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def issue_token(user_id: int, secret: str, now: datetime, ttl_seconds: int) -> str:
    claims = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(claims, secret, algorithm=_ALGORITHM)


def decode_token(token: str, secret: str, now: datetime) -> int:
    """Return the user id in ``token``; expiry is judged against ``now``, not the OS clock."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            options={"verify_exp": False, "verify_iat": False},
        )
        user_id = int(claims["sub"])
        expires = int(claims["exp"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise AuthenticationError("invalid token") from exc
    if now.timestamp() >= expires:
        raise AuthenticationError("token expired")
    return user_id
