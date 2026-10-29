"""Shared fixtures. Time is frozen, randomness is seeded, the database is a per-test file."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.main import create_app
from app.models import Product, StockLevel
from app.services import auth_service

FROZEN_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


class FrozenClock:
    def __init__(self, start: datetime = FROZEN_NOW) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


@pytest.fixture(autouse=True)
def _seed_randomness() -> None:
    random.seed(20250115)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key="test-secret",
        password_cost_exp=4,
    )


@pytest.fixture
def app(settings: Settings, clock: FrozenClock) -> Iterator[FastAPI]:
    application = create_app(settings, clock)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def session_factory(app: FastAPI) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = app.state.session_factory
    return factory


@dataclass
class World:
    """Three users (admin id 1, alice id 2, bob id 3) and three stocked products."""

    client: TestClient
    session_factory: sessionmaker[Session]
    product_ids: dict[str, int]

    def headers(self, who: str) -> dict[str, str]:
        resp = self.client.post(
            "/auth/token", json={"email": f"{who}@example.com", "password": PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def order(self, who: str, lines: list[tuple[str, int]]) -> dict[str, object]:
        body = {"items": [{"product_id": self.product_ids[sku], "quantity": q} for sku, q in lines]}
        resp = self.client.post("/orders", json=body, headers=self.headers(who))
        assert resp.status_code == 201, resp.text
        data: dict[str, object] = resp.json()
        return data

    def stock(self, sku: str) -> tuple[int, int]:
        with self.session_factory() as db:
            row = db.get(StockLevel, self.product_ids[sku])
            assert row is not None
            return row.on_hand, row.reserved


@pytest.fixture
def world(app: FastAPI, client: TestClient, settings: Settings, clock: FrozenClock) -> World:
    factory: sessionmaker[Session] = app.state.session_factory
    with factory() as db:
        auth_service.create_user(db, settings, clock, "admin@example.com", PASSWORD, role="admin")
        auth_service.create_user(db, settings, clock, "alice@example.com", PASSWORD)
        auth_service.create_user(db, settings, clock, "bob@example.com", PASSWORD)
        ids: dict[str, int] = {}
        for sku, name, price, qty in [
            ("WIDGET", "Widget", 1000, 10),
            ("GADGET", "Gadget", 2500, 5),
            ("GIZMO", "Gizmo", 400, 3),
        ]:
            product = Product(sku=sku, name=name, price_cents=price, active=True)
            db.add(product)
            db.flush()
            db.add(StockLevel(product_id=product.id, on_hand=qty, reserved=0))
            ids[sku] = product.id
        db.commit()
    return World(client, factory, ids)


@pytest.fixture
def make_products(world: World) -> Callable[[int], None]:
    """Insert ``n`` extra products named Item 001.. so list endpoints have something to page."""

    def _make(n: int) -> None:
        with world.session_factory() as db:
            for i in range(1, n + 1):
                db.add(
                    Product(
                        sku=f"ITEM{i:03d}", name=f"Item {i:03d}", price_cents=100 + i, active=True
                    )
                )
            db.commit()

    return _make
