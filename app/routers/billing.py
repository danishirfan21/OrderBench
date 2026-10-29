from __future__ import annotations

from fastapi import APIRouter

from app.deps import DB, AdminUser, ClockDep, CurrentUser, ensure_owner_or_admin
from app.errors import NotFoundError
from app.models import Plan
from app.repositories import BillingRepository
from app.schemas import ChangePlanIn, PlanCreate, PlanOut, SubscriptionCreate, SubscriptionOut
from app.services import billing_service

router = APIRouter(prefix="/billing", tags=["billing"])


def _plan(db: DB, plan_id: int) -> Plan:
    plan = BillingRepository(db).get_plan(plan_id)
    if plan is None:
        raise NotFoundError(f"plan {plan_id} not found")
    return plan


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: DB) -> list[PlanOut]:
    return [PlanOut.model_validate(p) for p in BillingRepository(db).list_plans()]


@router.post("/plans", response_model=PlanOut, status_code=201)
def create_plan(body: PlanCreate, db: DB, _admin: AdminUser) -> PlanOut:
    plan = BillingRepository(db).add_plan(
        Plan(name=body.name, monthly_price_cents=body.monthly_price_cents)
    )
    db.commit()
    return PlanOut.model_validate(plan)


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def subscribe(
    body: SubscriptionCreate, db: DB, user: CurrentUser, clock: ClockDep
) -> SubscriptionOut:
    sub = billing_service.subscribe(db, user, _plan(db, body.plan_id), clock.now())
    return SubscriptionOut.model_validate(sub)


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionOut)
def get_subscription(subscription_id: int, db: DB, user: CurrentUser) -> SubscriptionOut:
    sub = billing_service.get_subscription(db, subscription_id)
    ensure_owner_or_admin(user, sub.user_id)
    return SubscriptionOut.model_validate(sub)


@router.post("/subscriptions/{subscription_id}/renew", response_model=SubscriptionOut)
def renew(subscription_id: int, db: DB, user: CurrentUser, clock: ClockDep) -> SubscriptionOut:
    sub = billing_service.get_subscription(db, subscription_id)
    ensure_owner_or_admin(user, sub.user_id)
    return SubscriptionOut.model_validate(billing_service.renew(db, sub, clock.now()))


@router.post("/subscriptions/{subscription_id}/change-plan", response_model=SubscriptionOut)
def change_plan(
    subscription_id: int, body: ChangePlanIn, db: DB, user: CurrentUser, clock: ClockDep
) -> SubscriptionOut:
    sub = billing_service.get_subscription(db, subscription_id)
    ensure_owner_or_admin(user, sub.user_id)
    new_plan = _plan(db, body.plan_id)
    return SubscriptionOut.model_validate(
        billing_service.change_plan(db, sub, new_plan, clock.now())
    )
