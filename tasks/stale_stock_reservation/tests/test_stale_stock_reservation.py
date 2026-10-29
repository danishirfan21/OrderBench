from __future__ import annotations

import pytest

from app.errors import InsufficientStockError
from app.models import Order, StockLevel
from app.services import inventory_service
from tests.conftest import FROZEN_NOW, World


def _make_orders(world: World, n: int) -> list[int]:
    with world.session_factory() as db:
        orders = [Order(user_id=2, status="pending", total_cents=0, created_at=FROZEN_NOW) for _ in range(n)]
        db.add_all(orders)
        db.commit()
        return [o.id for o in orders]


def test_a_stale_session_cannot_oversell(world: World) -> None:
    pid = world.product_ids["GADGET"]  # 5 on hand
    first, second = _make_orders(world, 2)
    session_a, session_b = world.session_factory(), world.session_factory()
    try:
        assert session_a.get(StockLevel, pid) is not None  # checkout A has looked at the stock
        inventory_service.reserve(session_b, pid, 4, first, FROZEN_NOW, 900)
        session_b.commit()  # checkout B reserves 4 of 5 in the meantime
        with pytest.raises(InsufficientStockError):
            inventory_service.reserve(session_a, pid, 4, second, FROZEN_NOW, 900)
        session_a.rollback()
    finally:
        session_a.close()
        session_b.close()
    assert world.stock("GADGET") == (5, 4)


def test_a_stale_session_does_not_erase_a_concurrent_reservation(world: World) -> None:
    pid = world.product_ids["GADGET"]
    first, second = _make_orders(world, 2)
    session_a, session_b = world.session_factory(), world.session_factory()
    try:
        assert session_a.get(StockLevel, pid) is not None
        inventory_service.reserve(session_b, pid, 2, first, FROZEN_NOW, 900)
        session_b.commit()
        inventory_service.reserve(session_a, pid, 2, second, FROZEN_NOW, 900)
        session_a.commit()
    finally:
        session_a.close()
        session_b.close()
    assert world.stock("GADGET") == (5, 4)  # both holds counted
