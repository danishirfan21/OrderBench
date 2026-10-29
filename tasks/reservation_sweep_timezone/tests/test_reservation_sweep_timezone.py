from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FrozenClock, World


def _client(world: World) -> TestClient:
    return TestClient(world.client.app, raise_server_exceptions=False)  # type: ignore[arg-type]


def _sweep(world: World) -> tuple[int, dict[str, int]]:
    resp = _client(world).post("/admin/reservations/sweep", headers=world.headers("admin"))
    return resp.status_code, resp.json()


def test_sweep_releases_expired_reservations(world: World, clock: FrozenClock) -> None:
    order = world.order("alice", [("WIDGET", 4)])
    clock.advance(seconds=901)
    status, body = _sweep(world)
    assert (status, body) == (200, {"expired": 1})
    assert world.stock("WIDGET") == (10, 0)
    fetched = world.client.get(f"/orders/{order['id']}", headers=world.headers("alice")).json()
    assert fetched["status"] == "expired"


def test_sweep_keeps_live_reservations(world: World, clock: FrozenClock) -> None:
    world.order("alice", [("WIDGET", 4)])
    clock.advance(seconds=899)
    assert _sweep(world) == (200, {"expired": 0})
    assert world.stock("WIDGET") == (10, 4)


def test_reservation_expires_exactly_at_its_deadline(world: World, clock: FrozenClock) -> None:
    world.order("alice", [("WIDGET", 4)])
    clock.advance(seconds=900)
    assert _sweep(world) == (200, {"expired": 1})


def test_committed_reservations_survive_the_sweep(world: World, clock: FrozenClock) -> None:
    order = world.order("alice", [("WIDGET", 4)])
    world.client.post(f"/orders/{order['id']}/pay", headers=world.headers("alice"))
    clock.advance(hours=3)
    assert _sweep(world) == (200, {"expired": 0})
    assert world.stock("WIDGET") == (10, 4)


def test_active_listing_reports_time_remaining(world: World, clock: FrozenClock) -> None:
    world.order("alice", [("WIDGET", 4)])
    clock.advance(seconds=100)
    resp = _client(world).get("/admin/reservations", headers=world.headers("admin"))
    assert resp.status_code == 200
    assert [r["seconds_remaining"] for r in resp.json()] == [800]
    clock.advance(seconds=800)
    resp = _client(world).get("/admin/reservations", headers=world.headers("admin"))
    assert resp.json() == []
