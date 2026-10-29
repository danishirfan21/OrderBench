"""Registration, login and token resolution."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.errors import AuthenticationError, ConflictError
from app.models import User
from app.repositories import UserRepository
from app.security import decode_token, hash_password, issue_token, verify_password

# Verified against when the email is unknown so both failures cost the same.
_DUMMY_HASH = hash_password("not-a-real-password", cost_exp=4)


def create_user(
    db: Session, settings: Settings, clock: Clock, email: str, password: str, role: str = "customer"
) -> User:
    users = UserRepository(db)
    email = email.lower()
    if users.get_by_email(email) is not None:
        raise ConflictError("email already registered")
    user = User(
        email=email,
        password_hash=hash_password(password, settings.password_cost_exp),
        role=role,
        is_active=True,
        created_at=clock.now(),
    )
    users.add(user)
    db.commit()
    return user


def login(
    db: Session, settings: Settings, clock: Clock, email: str, password: str
) -> tuple[str, int]:
    user = UserRepository(db).get_by_email(email)
    stored = user.password_hash if user is not None else _DUMMY_HASH
    ok = verify_password(password, stored)
    if user is None or not ok or not user.is_active:
        raise AuthenticationError("invalid email or password")
    token = issue_token(user.id, settings.secret_key, clock.now(), settings.token_ttl_seconds)
    return token, settings.token_ttl_seconds


def user_from_token(db: Session, settings: Settings, clock: Clock, token: str) -> User:
    user_id = decode_token(token, settings.secret_key, clock.now())
    user = UserRepository(db).get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("invalid token")
    return user
