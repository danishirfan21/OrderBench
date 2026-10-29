from __future__ import annotations

from collections.abc import Callable

from tests.conftest import World


def test_first_page_starts_at_first_record(
    world: World, make_products: Callable[[int], None]
) -> None:
    make_products(47)
    body = world.client.get("/products", params={"size": 10}).json()
    assert len(body["items"]) == 10
    assert [p["name"] for p in body["items"][:3]] == ["Widget", "Gadget", "Gizmo"]


def test_pages_partition_the_catalogue(world: World, make_products: Callable[[int], None]) -> None:
    make_products(47)
    seen: list[int] = []
    for page in range(1, 6):
        body = world.client.get("/products", params={"size": 10, "page": page}).json()
        assert len(body["items"]) == 10, f"page {page}"
        seen.extend(p["id"] for p in body["items"])
    assert seen == sorted(seen)
    assert len(set(seen)) == 50


def test_last_page_holds_the_remainder(world: World, make_products: Callable[[int], None]) -> None:
    make_products(22)  # 25 products total
    last = world.client.get("/products", params={"size": 10, "page": 3}).json()
    assert len(last["items"]) == 5
    assert last["items"][-1]["name"] == "Item 022"


def test_order_listing_first_page_is_newest(world: World) -> None:
    for _ in range(3):
        world.order("alice", [("WIDGET", 1)])
    headers = world.headers("alice")
    first = world.client.get("/orders", params={"size": 2}, headers=headers).json()
    second = world.client.get("/orders", params={"size": 2, "page": 2}, headers=headers).json()
    assert [o["id"] for o in first["items"]] == [3, 2]
    assert [o["id"] for o in second["items"]] == [1]
