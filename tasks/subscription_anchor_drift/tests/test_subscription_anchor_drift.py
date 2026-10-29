from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import FrozenClock, World


def _plan(world: World, name: str, price: int) -> int:
    resp = world.client.post(
        "/billing/plans",
        json={"name": name, "monthly_price_cents": price},
        headers=world.headers("admin"),
    )
    return int(resp.json()["id"])


def _subscribe(world: World, clock: FrozenClock, start: datetime, plan_id: int) -> int:
    clock.set(start)
    resp = world.client.post(
        "/billing/subscriptions", json={"plan_id": plan_id}, headers=world.headers("alice")
    )
    return int(resp.json()["id"])


def _renew(world: World, clock: FrozenClock, sub_id: int, at: datetime) -> dict[str, Any]:
    clock.set(at)
    resp = world.client.post(
        f"/billing/subscriptions/{sub_id}/renew", headers=world.headers("alice")
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _utc(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 12, 0, tzinfo=UTC)


def test_clamped_month_does_not_shift_later_periods(world: World, clock: FrozenClock) -> None:
    sub_id = _subscribe(world, clock, _utc(2025, 1, 31), _plan(world, "Basic", 3000))
    feb = _renew(world, clock, sub_id, _utc(2025, 2, 28))
    assert feb["period_start"].startswith("2025-02-28T12:00:00")
    assert feb["period_end"].startswith("2025-03-31T12:00:00")
    mar = _renew(world, clock, sub_id, _utc(2025, 3, 31))
    assert mar["period_start"].startswith("2025-03-31T12:00:00")
    assert mar["period_end"].startswith("2025-04-30T12:00:00")
    apr = _renew(world, clock, sub_id, _utc(2025, 4, 30))
    assert apr["period_end"].startswith("2025-05-31T12:00:00")


def test_proration_in_a_31_day_period_after_a_short_month(world: World, clock: FrozenClock) -> None:
    basic, pro = _plan(world, "Basic", 3000), _plan(world, "Pro", 6000)
    sub_id = _subscribe(world, clock, _utc(2025, 1, 31), basic)
    _renew(world, clock, sub_id, _utc(2025, 2, 28))  # period Feb 28 -> Mar 31 (31 days)
    clock.set(_utc(2025, 3, 16))  # 15 of 31 days remain
    resp = world.client.post(
        f"/billing/subscriptions/{sub_id}/change-plan",
        json={"plan_id": pro},
        headers=world.headers("alice"),
    )
    assert resp.status_code == 200
    last = resp.json()["invoices"][-1]
    assert (last["kind"], last["amount_cents"]) == ("proration", 1452)  # 3000 * 15 / 31


def test_leap_year_clamp_returns_to_the_anchor(world: World, clock: FrozenClock) -> None:
    sub_id = _subscribe(world, clock, _utc(2024, 1, 30), _plan(world, "Basic", 3000))
    feb = _renew(world, clock, sub_id, _utc(2024, 2, 29))
    assert feb["period_end"].startswith("2024-03-30T12:00:00")
    mar = _renew(world, clock, sub_id, _utc(2024, 3, 30))
    assert mar["period_end"].startswith("2024-04-30T12:00:00")
