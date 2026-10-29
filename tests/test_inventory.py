from __future__ import annotations

from sqlalchemy import select

from app.models import Reservation
from app.services import inventory_service
from tests.conftest import FROZEN_NOW, World


def test_reservation_records_expiry_from_the_clock(world: World) -> None:
    world.order("alice", [("WIDGET", 2), ("GADGET", 1)])
    with world.session_factory() as db:
        rows = db.scalars(select(Reservation).order_by(Reservation.id)).all()
        assert [(r.quantity, r.status) for r in rows] == [(2, "active"), (1, "active")]
        # sqlite drops tzinfo; the wall time must still be now + ttl
        assert rows[0].expires_at.replace(tzinfo=None) == (
            FROZEN_NOW.replace(tzinfo=None).replace(minute=15)
        )


def test_sequential_reservations_never_oversell(world: World) -> None:
    world.order("alice", [("GADGET", 3)])
    world.order("bob", [("GADGET", 2)])
    assert world.stock("GADGET") == (5, 5)
    resp = world.client.post(
        "/orders",
        json={"items": [{"product_id": world.product_ids["GADGET"], "quantity": 1}]},
        headers=world.headers("alice"),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "insufficient_stock"


def test_reserving_against_a_missing_stock_row_is_not_found(world: World) -> None:
    from app.errors import NotFoundError

    with world.session_factory() as db:
        try:
            inventory_service.reserve(db, 4242, 1, 1, FROZEN_NOW, 60)
        except NotFoundError:
            return
    raise AssertionError("expected NotFoundError")


def test_admin_endpoints_require_admin(world: World) -> None:
    alice = world.headers("alice")
    assert world.client.get("/admin/reservations", headers=alice).status_code == 403
    assert world.client.post("/admin/reservations/sweep", headers=alice).status_code == 403


def test_sweep_with_nothing_reserved_is_a_noop(world: World) -> None:
    resp = world.client.post("/admin/reservations/sweep", headers=world.headers("admin"))
    assert resp.json() == {"expired": 0}
    assert world.client.get("/admin/reservations", headers=world.headers("admin")).json() == []


def test_paid_orders_hold_stock_past_the_ttl_window(world: World) -> None:
    order = world.order("alice", [("WIDGET", 2)])
    world.client.post(f"/orders/{order['id']}/pay", headers=world.headers("admin"))
    with world.session_factory() as db:
        assert [r.status for r in db.scalars(select(Reservation)).all()] == ["committed"]
