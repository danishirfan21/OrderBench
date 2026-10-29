"""Subscriptions and proration. See DOMAIN.md, section "Billing"."""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction

from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models import Invoice, Plan, Subscription, User
from app.repositories import BillingRepository
from app.timeutil import add_months, as_utc


def round_half_up(value: Fraction) -> int:
    """Round to the nearest integer, ties away from zero (so -0.5 -> -1, 0.5 -> 1)."""
    sign = -1 if value < 0 else 1
    magnitude = abs(value)
    return sign * int(magnitude + Fraction(1, 2))


def subscribe(db: Session, user: User, plan: Plan, now: datetime) -> Subscription:
    repo = BillingRepository(db)
    start = as_utc(now)
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        anchor_day=start.day,
        period_start=start,
        period_end=add_months(start, 1, start.day),
        status="active",
    )
    repo.add_subscription(sub)
    repo.add_invoice(
        Invoice(
            subscription_id=sub.id,
            kind="initial",
            amount_cents=plan.monthly_price_cents,
            description=f"{plan.name} first period",
            created_at=start,
        )
    )
    db.commit()
    return sub


def get_subscription(db: Session, subscription_id: int) -> Subscription:
    sub = BillingRepository(db).get_subscription(subscription_id)
    if sub is None:
        raise NotFoundError(f"subscription {subscription_id} not found")
    return sub


def renew(db: Session, sub: Subscription, now: datetime) -> Subscription:
    """Advance to the next period if the current one has ended; bills the plan price."""
    if sub.status != "active":
        raise ConflictError("subscription is not active")
    if as_utc(now) < as_utc(sub.period_end):
        raise ConflictError("current period has not ended")
    new_start = as_utc(sub.period_end)
    sub.period_start = new_start
    sub.period_end = add_months(new_start, 1, sub.anchor_day)
    BillingRepository(db).add_invoice(
        Invoice(
            subscription_id=sub.id,
            kind="renewal",
            amount_cents=sub.plan.monthly_price_cents,
            description=f"{sub.plan.name} renewal",
            created_at=as_utc(now),
        )
    )
    db.commit()
    return sub


def proration_net_cents(
    old_price: int, new_price: int, period_start: datetime, period_end: datetime, at: datetime
) -> int:
    """Net amount for switching plans at ``at``: charge for the new plan's remaining
    share of the period minus credit for the old plan's unused share, rounded once."""
    total = (as_utc(period_end) - as_utc(period_start)).total_seconds()
    remaining = (as_utc(period_end) - as_utc(at)).total_seconds()
    share = Fraction(remaining) / Fraction(total)
    return round_half_up((new_price - old_price) * share)


def change_plan(db: Session, sub: Subscription, new_plan: Plan, now: datetime) -> Subscription:
    if sub.status != "active":
        raise ConflictError("subscription is not active")
    at = as_utc(now)
    if not (as_utc(sub.period_start) <= at < as_utc(sub.period_end)):
        raise ConflictError("current period has ended; renew before changing plans")
    if new_plan.id == sub.plan_id:
        raise ConflictError("already on this plan")
    amount = proration_net_cents(
        sub.plan.monthly_price_cents,
        new_plan.monthly_price_cents,
        sub.period_start,
        sub.period_end,
        at,
    )
    BillingRepository(db).add_invoice(
        Invoice(
            subscription_id=sub.id,
            kind="proration",
            amount_cents=amount,
            description=f"{sub.plan.name} -> {new_plan.name}",
            created_at=at,
        )
    )
    sub.plan_id = new_plan.id
    sub.plan = new_plan
    db.commit()
    return sub
