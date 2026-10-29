from __future__ import annotations

from datetime import UTC, datetime
from fractions import Fraction

import pytest

from app.services.billing_service import proration_net_cents, round_half_up
from app.timeutil import add_months
from tests.conftest import FrozenClock, World


def _plan(world: World, name: str, price: int) -> int:
    resp = world.client.post(
        "/billing/plans",
        json={"name": name, "monthly_price_cents": price},
        headers=world.headers("admin"),
    )
    assert resp.status_code == 201
    return int(resp.json()["id"])


def _subscribe(world: World, who: str, plan_id: int) -> dict[str, object]:
    resp = world.client.post(
        "/billing/subscriptions", json={"plan_id": plan_id}, headers=world.headers(who)
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, object] = resp.json()
    return body


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(1, 2), 1),
        (Fraction(-1, 2), -1),
        (Fraction(49, 100), 0),
        (Fraction(151, 100), 2),
        (Fraction(-151, 100), -2),
    ],
)
def test_round_half_up(value: Fraction, expected: int) -> None:
    assert round_half_up(value) == expected


def test_add_months_clamps_to_month_length() -> None:
    jan31 = datetime(2025, 1, 31, 9, 30, tzinfo=UTC)
    assert add_months(jan31, 1, 31) == datetime(2025, 2, 28, 9, 30, tzinfo=UTC)
    assert add_months(jan31, 2, 31) == datetime(2025, 3, 31, 9, 30, tzinfo=UTC)
    assert add_months(datetime(2025, 12, 15, tzinfo=UTC), 1, 15) == datetime(
        2026, 1, 15, tzinfo=UTC
    )
    assert add_months(datetime(2024, 1, 31, tzinfo=UTC), 1, 31) == datetime(2024, 2, 29, tzinfo=UTC)


def test_proration_unit_half_period() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 31, tzinfo=UTC)
    mid = datetime(2025, 1, 16, tzinfo=UTC)
    assert proration_net_cents(1000, 3000, start, end, mid) == 1000
    assert proration_net_cents(3000, 1000, start, end, mid) == -1000


def test_only_admin_creates_plans(world: World) -> None:
    resp = world.client.post(
        "/billing/plans",
        json={"name": "x", "monthly_price_cents": 5},
        headers=world.headers("alice"),
    )
    assert resp.status_code == 403
    _plan(world, "Basic", 3000)
    assert [p["name"] for p in world.client.get("/billing/plans").json()] == ["Basic"]


def test_subscribe_sets_first_period_and_invoice(world: World) -> None:
    sub = _subscribe(world, "alice", _plan(world, "Basic", 3000))
    assert sub["anchor_day"] == 15
    assert str(sub["period_start"]).startswith("2025-01-15T12:00:00")
    assert str(sub["period_end"]).startswith("2025-02-15T12:00:00")
    assert [(i["kind"], i["amount_cents"]) for i in sub["invoices"]] == [("initial", 3000)]  # type: ignore[attr-defined]


def test_renewal_requires_period_end(world: World, clock: FrozenClock) -> None:
    sub = _subscribe(world, "alice", _plan(world, "Basic", 3000))
    url = f"/billing/subscriptions/{sub['id']}/renew"
    assert world.client.post(url, headers=world.headers("alice")).status_code == 409
    clock.set(datetime(2025, 2, 15, 12, 0, tzinfo=UTC))
    resp = world.client.post(url, headers=world.headers("alice"))
    assert resp.status_code == 200
    assert str(resp.json()["period_end"]).startswith("2025-03-15T12:00:00")
    assert resp.json()["invoices"][-1]["kind"] == "renewal"


def test_upgrade_mid_period_prorates_to_the_second(world: World, clock: FrozenClock) -> None:
    basic, pro = _plan(world, "Basic", 3000), _plan(world, "Pro", 6000)
    sub = _subscribe(world, "alice", basic)
    clock.set(datetime(2025, 1, 30, 12, 0, tzinfo=UTC))  # 16 of 31 days remain
    resp = world.client.post(
        f"/billing/subscriptions/{sub['id']}/change-plan",
        json={"plan_id": pro},
        headers=world.headers("alice"),
    )
    assert resp.status_code == 200
    last = resp.json()["invoices"][-1]
    assert (last["kind"], last["amount_cents"]) == ("proration", 1548)  # 3000 * 16 / 31
    assert resp.json()["plan_id"] == pro


def test_downgrade_produces_a_credit(world: World, clock: FrozenClock) -> None:
    basic, pro = _plan(world, "Basic", 3000), _plan(world, "Pro", 6000)
    sub = _subscribe(world, "alice", pro)
    clock.set(datetime(2025, 1, 30, 12, 0, tzinfo=UTC))
    resp = world.client.post(
        f"/billing/subscriptions/{sub['id']}/change-plan",
        json={"plan_id": basic},
        headers=world.headers("alice"),
    )
    assert resp.json()["invoices"][-1]["amount_cents"] == -1548


def test_change_plan_edge_cases(world: World, clock: FrozenClock) -> None:
    basic, pro = _plan(world, "Basic", 3000), _plan(world, "Pro", 6000)
    sub = _subscribe(world, "alice", basic)
    url = f"/billing/subscriptions/{sub['id']}/change-plan"
    alice = world.headers("alice")
    assert world.client.post(url, json={"plan_id": basic}, headers=alice).status_code == 409
    assert world.client.post(url, json={"plan_id": 999}, headers=alice).status_code == 404
    clock.set(datetime(2025, 2, 15, 12, 0, tzinfo=UTC))  # exactly the period end
    alice = world.headers("alice")
    assert world.client.post(url, json={"plan_id": pro}, headers=alice).status_code == 409


def test_subscriptions_are_private(world: World) -> None:
    sub = _subscribe(world, "alice", _plan(world, "Basic", 3000))
    url = f"/billing/subscriptions/{sub['id']}"
    assert world.client.get(url, headers=world.headers("bob")).status_code == 403
    assert world.client.get(url, headers=world.headers("alice")).status_code == 200
    assert world.client.get(url, headers=world.headers("admin")).status_code == 200
