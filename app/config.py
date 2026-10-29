"""Runtime configuration, read from ORDERBENCH_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./orderbench.db"
    secret_key: str = "dev-secret-change-me"
    token_ttl_seconds: int = 3600
    reservation_ttl_seconds: int = 900
    # scrypt work factor exponent (cost = 2**n). Tests lower this for speed.
    password_cost_exp: int = 14
    max_page_size: int = 100


def get_settings() -> Settings:
    env = os.environ
    return Settings(
        database_url=env.get("ORDERBENCH_DATABASE_URL", Settings.database_url),
        secret_key=env.get("ORDERBENCH_SECRET_KEY", Settings.secret_key),
        token_ttl_seconds=int(env.get("ORDERBENCH_TOKEN_TTL", Settings.token_ttl_seconds)),
        reservation_ttl_seconds=int(
            env.get("ORDERBENCH_RESERVATION_TTL", Settings.reservation_ttl_seconds)
        ),
    )
