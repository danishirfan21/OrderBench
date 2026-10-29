from __future__ import annotations

from tests.conftest import World


def _create(world: World, who: str, **over: object) -> int:
    body = {"sku": " new-1 ", "name": "New thing", "price_cents": 999, "initial_stock": 4, **over}
    headers = world.headers(who) if who else {}
    return world.client.post("/products", json=body, headers=headers).status_code


def test_only_admin_creates_products(world: World) -> None:
    assert _create(world, "") == 401
    assert _create(world, "alice") == 403
    assert _create(world, "admin") == 201


def test_sku_is_normalised_and_unique(world: World) -> None:
    headers = world.headers("admin")
    first = world.client.post(
        "/products", json={"sku": " new-1 ", "name": "N", "price_cents": 5}, headers=headers
    )
    assert first.json()["sku"] == "NEW-1"
    again = world.client.post(
        "/products", json={"sku": "NEW-1", "name": "N", "price_cents": 5}, headers=headers
    )
    assert again.status_code == 409


def test_invalid_product_payloads_rejected(world: World) -> None:
    assert _create(world, "admin", price_cents=0) == 422
    assert _create(world, "admin", initial_stock=-1) == 422
    assert _create(world, "admin", name="") == 422


def test_get_product_and_404(world: World) -> None:
    pid = world.product_ids["WIDGET"]
    assert world.client.get(f"/products/{pid}").json()["sku"] == "WIDGET"
    assert world.client.get("/products/9999").status_code == 404


def test_filter_totals(world: World) -> None:
    get = world.client.get
    assert get("/products", params={"min_price": 1000}).json()["total"] == 2
    assert get("/products", params={"max_price": 999}).json()["total"] == 1
    assert get("/products", params={"q": "GAD"}).json()["total"] == 1
    assert get("/products", params={"active": "false"}).json()["total"] == 0


def test_bad_sort_rejected(world: World) -> None:
    assert world.client.get("/products", params={"sort": "colour"}).status_code == 422


def test_stock_view_and_update(world: World) -> None:
    pid = world.product_ids["WIDGET"]
    alice, admin = world.headers("alice"), world.headers("admin")
    view = world.client.get(f"/products/{pid}/stock", headers=alice).json()
    assert view == {"product_id": pid, "on_hand": 10, "reserved": 0, "available": 10}
    denied = world.client.put(f"/products/{pid}/stock", json={"on_hand": 20}, headers=alice)
    assert denied.status_code == 403
    updated = world.client.put(f"/products/{pid}/stock", json={"on_hand": 20}, headers=admin)
    assert updated.json()["available"] == 20
    assert world.client.get(f"/products/{pid}/stock").status_code == 401


def test_stock_cannot_drop_below_reserved(world: World) -> None:
    world.order("alice", [("WIDGET", 6)])
    pid = world.product_ids["WIDGET"]
    resp = world.client.put(
        f"/products/{pid}/stock", json={"on_hand": 5}, headers=world.headers("admin")
    )
    assert resp.status_code == 409
