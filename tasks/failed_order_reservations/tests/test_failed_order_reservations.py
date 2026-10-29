from __future__ import annotations

from sqlalchemy import func, select

from app.models import Order, Reservation
from tests.conftest import World


def _oversized_order(world: World) -> int:
    body = {
        "items": [
            {"product_id": world.product_ids["WIDGET"], "quantity": 4},
            {"product_id": world.product_ids["GADGET"], "quantity": 2},
            {"product_id": world.product_ids["GIZMO"], "quantity": 50},
        ]
    }
    resp = world.client.post("/orders", json=body, headers=world.headers("alice"))
    return int(resp.status_code)


def test_rejected_order_holds_no_stock(world: World) -> None:
    assert _oversized_order(world) == 409
    assert world.stock("WIDGET") == (10, 0)
    assert world.stock("GADGET") == (5, 0)
    assert world.stock("GIZMO") == (3, 0)


def test_rejected_order_leaves_no_order_or_reservation_rows(world: World) -> None:
    assert _oversized_order(world) == 409
    with world.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(func.count()).select_from(Reservation)) == 0
    assert world.client.get("/orders", headers=world.headers("alice")).json()["total"] == 0


def test_stock_is_still_sellable_after_a_rejection(world: World) -> None:
    assert _oversized_order(world) == 409
    data = world.order("bob", [("WIDGET", 10), ("GADGET", 5)])
    assert data["status"] == "pending"
    assert world.stock("WIDGET") == (10, 10)
    assert world.stock("GADGET") == (5, 5)
