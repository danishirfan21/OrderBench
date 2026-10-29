from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import User
from tests.conftest import PASSWORD, FrozenClock, World


def test_register_creates_customer(client: TestClient) -> None:
    resp = client.post("/auth/register", json={"email": "New@Example.com", "password": PASSWORD})
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "customer"
    assert "password" not in body and "password_hash" not in body


def test_register_duplicate_email_conflicts(world: World) -> None:
    resp = world.client.post(
        "/auth/register", json={"email": "ALICE@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 409


def test_register_rejects_bad_email_and_short_password(client: TestClient) -> None:
    bad_email = client.post("/auth/register", json={"email": "nope", "password": PASSWORD})
    short_pw = client.post("/auth/register", json={"email": "a@b.co", "password": "short"})
    assert bad_email.status_code == 422
    assert short_pw.status_code == 422


def test_password_is_stored_hashed(world: World, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as db:
        user = db.query(User).filter_by(email="alice@example.com").one()
        assert PASSWORD not in user.password_hash
        assert user.password_hash.startswith("scrypt$")


def test_login_and_me(world: World) -> None:
    resp = world.client.get("/auth/me", headers=world.headers("alice"))
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"


def test_login_failures_are_indistinguishable(world: World) -> None:
    wrong = world.client.post(
        "/auth/token", json={"email": "alice@example.com", "password": "x" * 12}
    )
    unknown = world.client.post(
        "/auth/token", json={"email": "ghost@example.com", "password": "x" * 12}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_missing_or_garbage_token_is_rejected(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_token_expires_on_the_injected_clock(world: World, clock: FrozenClock) -> None:
    headers = world.headers("alice")
    assert world.client.get("/auth/me", headers=headers).status_code == 200
    clock.advance(seconds=3599)
    assert world.client.get("/auth/me", headers=headers).status_code == 200
    clock.advance(seconds=1)
    assert world.client.get("/auth/me", headers=headers).status_code == 401
