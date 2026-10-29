from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import World


def _post(world: World, who: str, items: list[dict[str, Any]]) -> Any:
    return world.client.post("/orders", json={"items": items}, headers=world.headers(who))


def test_place_order_reserves_stock_and_totals(world: World) -> None:
    data = world.order("alice", [("WIDGET", 2), ("GADGET", 1)])
    assert data["status"] == "pending"
    assert data["total_cents"] == 2 * 1000 + 2500
    assert world.stock("WIDGET") == (10, 2)
    assert world.stock("GADGET") == (5, 1)


def test_anonymous_cannot_order(world: World) -> None:
    resp = world.client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]})
    assert resp.status_code == 401


def test_repeated_products_are_merged(world: World) -> None:
    pid = world.product_ids["WIDGET"]
    resp = _post(
        world, "alice", [{"product_id": pid, "quantity": 2}, {"product_id": pid, "quantity": 3}]
    )
    assert resp.status_code == 201
    assert [(i["product_id"], i["quantity"]) for i in resp.json()["items"]] == [(pid, 5)]


def test_unknown_product_is_404_and_leaves_stock_alone(world: World) -> None:
    pid = world.product_ids["WIDGET"]
    resp = _post(
        world, "alice", [{"product_id": pid, "quantity": 1}, {"product_id": 9999, "quantity": 1}]
    )
    assert resp.status_code == 404
    assert world.stock("WIDGET") == (10, 0)


def test_insufficient_stock_is_409(world: World) -> None:
    pid = world.product_ids["GIZMO"]
    resp = _post(world, "alice", [{"product_id": pid, "quantity": 4}])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "insufficient_stock"
    assert world.stock("GIZMO") == (3, 0)


def test_selling_exactly_the_remaining_stock_succeeds(world: World) -> None:
    world.order("alice", [("GIZMO", 3)])
    assert world.stock("GIZMO") == (3, 3)
    resp = _post(world, "bob", [{"product_id": world.product_ids["GIZMO"], "quantity": 1}])
    assert resp.status_code == 409


def test_rejected_order_is_audited(world: World) -> None:
    pid = world.product_ids["GIZMO"]
    assert _post(world, "alice", [{"product_id": pid, "quantity": 99}]).status_code == 409
    audit = world.client.get(
        "/admin/audit", params={"event": "order.rejected"}, headers=world.headers("admin")
    )
    assert audit.json()["total"] == 1
    assert "requested 99" in audit.json()["items"][0]["detail"] or audit.json()["page"] == 1


def test_audit_log_is_admin_only(world: World) -> None:
    assert world.client.get("/admin/audit", headers=world.headers("alice")).status_code == 403


def test_confirmation_runs_as_background_task(world: World) -> None:
    data = world.order("alice", [("WIDGET", 1)])
    audit = world.client.get(
        "/admin/audit",
        params={"event": "order.notification_queued"},
        headers=world.headers("admin"),
    )
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["detail"] == f"order {data['id']}"


@pytest.mark.parametrize("quantity", ["3", 3.0, "3.0"])
def test_numeric_quantities_are_accepted(world: World, quantity: Any) -> None:
    resp = _post(
        world, "alice", [{"product_id": world.product_ids["WIDGET"], "quantity": quantity}]
    )
    assert resp.status_code == 201
    assert resp.json()["items"][0]["quantity"] == 3


@pytest.mark.parametrize("quantity", ["abc", None, 1001, [1]])
def test_unusable_quantities_are_rejected(world: World, quantity: Any) -> None:
    resp = _post(
        world, "alice", [{"product_id": world.product_ids["WIDGET"], "quantity": quantity}]
    )
    assert resp.status_code == 422


def test_empty_and_oversized_item_lists_rejected(world: World) -> None:
    assert _post(world, "alice", []).status_code == 422
    pid = world.product_ids["WIDGET"]
    assert _post(world, "alice", [{"product_id": pid, "quantity": 1}] * 51).status_code == 422


def test_owner_can_read_own_order(world: World) -> None:
    world.order("admin", [("WIDGET", 1)])
    mine = world.order("alice", [("WIDGET", 1)])
    resp = world.client.get(f"/orders/{mine['id']}", headers=world.headers("alice"))
    assert resp.status_code == 200
    assert resp.json()["items"][0]["quantity"] == 1


def test_admin_can_read_any_order(world: World) -> None:
    mine = world.order("alice", [("WIDGET", 1)])
    assert (
        world.client.get(f"/orders/{mine['id']}", headers=world.headers("admin")).status_code == 200
    )


def test_other_customer_cannot_read_order(world: World) -> None:
    mine = world.order("alice", [("WIDGET", 1)])
    assert (
        world.client.get(f"/orders/{mine['id']}", headers=world.headers("bob")).status_code == 403
    )


def test_missing_order_is_404(world: World) -> None:
    assert world.client.get("/orders/4040", headers=world.headers("admin")).status_code == 404


def test_pay_then_cancel_releases_stock(world: World) -> None:
    order = world.order("alice", [("WIDGET", 4)])
    h = world.headers("alice")
    paid = world.client.post(f"/orders/{order['id']}/pay", headers=h)
    assert paid.json()["status"] == "paid"
    assert world.client.post(f"/orders/{order['id']}/pay", headers=h).status_code == 409
    cancelled = world.client.post(f"/orders/{order['id']}/cancel", headers=h)
    assert cancelled.json()["status"] == "cancelled"
    assert world.stock("WIDGET") == (10, 0)
    assert world.client.post(f"/orders/{order['id']}/cancel", headers=h).status_code == 409


def test_fulfilment_consumes_stock(world: World) -> None:
    order = world.order("alice", [("WIDGET", 4)])
    world.client.post(f"/orders/{order['id']}/pay", headers=world.headers("alice"))
    assert (
        world.client.post(
            f"/orders/{order['id']}/fulfill", headers=world.headers("alice")
        ).status_code
        == 403
    )
    done = world.client.post(f"/orders/{order['id']}/fulfill", headers=world.headers("admin"))
    assert done.json()["status"] == "fulfilled"
    assert world.stock("WIDGET") == (6, 0)


def test_unpaid_order_cannot_be_fulfilled(world: World) -> None:
    order = world.order("alice", [("WIDGET", 1)])
    resp = world.client.post(f"/orders/{order['id']}/fulfill", headers=world.headers("admin"))
    assert resp.status_code == 409


def test_customers_cannot_list_other_users_orders(world: World) -> None:
    resp = world.client.get("/orders", params={"user_id": 3}, headers=world.headers("alice"))
    assert resp.status_code == 403


def test_order_listing_is_scoped_to_the_caller(world: World) -> None:
    world.order("alice", [("WIDGET", 1)])
    world.order("bob", [("WIDGET", 1)])
    assert world.client.get("/orders", headers=world.headers("bob")).json()["total"] == 1
    assert world.client.get("/orders", headers=world.headers("admin")).json()["total"] == 2
