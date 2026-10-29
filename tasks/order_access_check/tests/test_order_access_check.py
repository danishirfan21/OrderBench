from __future__ import annotations

from tests.conftest import World


def _alice_orders(world: World) -> None:
    for _ in range(3):  # order ids 1..3; bob is user 3
        world.order("alice", [("WIDGET", 1)])


def test_owner_can_read_each_of_their_orders(world: World) -> None:
    _alice_orders(world)
    headers = world.headers("alice")
    for order_id in (1, 2, 3):
        assert world.client.get(f"/orders/{order_id}", headers=headers).status_code == 200


def test_other_customer_cannot_read_any_order(world: World) -> None:
    _alice_orders(world)
    headers = world.headers("bob")
    for order_id in (1, 2, 3):
        assert world.client.get(f"/orders/{order_id}", headers=headers).status_code == 403


def test_other_customer_cannot_cancel_or_pay(world: World) -> None:
    _alice_orders(world)
    bob = world.headers("bob")
    assert world.client.post("/orders/3/cancel", headers=bob).status_code == 403
    assert world.client.post("/orders/3/pay", headers=bob).status_code == 403
    still = world.client.get("/orders/3", headers=world.headers("alice")).json()
    assert still["status"] == "pending"
    assert world.stock("WIDGET") == (10, 3)


def test_admin_reads_everything(world: World) -> None:
    _alice_orders(world)
    admin = world.headers("admin")
    for order_id in (1, 2, 3):
        assert world.client.get(f"/orders/{order_id}", headers=admin).status_code == 200
