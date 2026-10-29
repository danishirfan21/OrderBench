from __future__ import annotations

from tests.conftest import World


def _seed(world: World) -> None:
    for _ in range(3):
        world.order("alice", [("WIDGET", 1), ("GADGET", 1), ("GIZMO", 1)])


def test_total_counts_orders_not_item_rows(world: World) -> None:
    _seed(world)
    body = world.client.get("/orders", params={"size": 10}, headers=world.headers("alice")).json()
    assert body["total"] == 3
    assert body["pages"] == 1
    assert [o["id"] for o in body["items"]] == [3, 2, 1]
    assert all(len(o["items"]) == 3 for o in body["items"])


def test_page_size_counts_orders(world: World) -> None:
    _seed(world)
    headers = world.headers("alice")
    first = world.client.get("/orders", params={"size": 2}, headers=headers).json()
    second = world.client.get("/orders", params={"size": 2, "page": 2}, headers=headers).json()
    assert [o["id"] for o in first["items"]] == [3, 2]
    assert [o["id"] for o in second["items"]] == [1]
    assert (first["total"], first["pages"]) == (3, 2)
    assert all(len(o["items"]) == 3 for o in first["items"] + second["items"])


def test_product_filter_still_counts_each_order_once(world: World) -> None:
    _seed(world)
    pid = world.product_ids["WIDGET"]
    body = world.client.get(
        "/orders", params={"product_id": pid}, headers=world.headers("alice")
    ).json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
