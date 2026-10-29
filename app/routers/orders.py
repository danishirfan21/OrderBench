from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request

from app.deps import (
    DB,
    AdminUser,
    ClockDep,
    CurrentUser,
    Pagination,
    SettingsDep,
    ensure_owner_or_admin,
)
from app.errors import PermissionDeniedError
from app.models import Order
from app.pagination import Page, make_page, offset_for
from app.schemas import OrderCreate, OrderOut
from app.services import order_service
from app.tasks import notify_order_placed

router = APIRouter(prefix="/orders", tags=["orders"])


def _load_authorized(db: DB, user: CurrentUser, order_id: int) -> Order:
    order = order_service.get_order(db, order_id)
    ensure_owner_or_admin(user, order.user_id)
    return order


@router.post("", response_model=OrderOut, status_code=201)
def create_order(
    body: OrderCreate,
    request: Request,
    background: BackgroundTasks,
    db: DB,
    user: CurrentUser,
    settings: SettingsDep,
    clock: ClockDep,
) -> OrderOut:
    order = order_service.place_order(
        db, user, body.items, clock.now(), settings.reservation_ttl_seconds
    )
    background.add_task(
        notify_order_placed, request.app.state.session_factory, clock, order.id, user.id
    )
    return OrderOut.model_validate(order)


@router.get("", response_model=Page[OrderOut])
def list_orders(
    db: DB,
    user: CurrentUser,
    paging: Pagination,
    status: str | None = None,
    product_id: int | None = None,
    user_id: int | None = None,
) -> Page[OrderOut]:
    if user.role != "admin":
        if user_id is not None and user_id != user.id:
            raise PermissionDeniedError("customers may only list their own orders")
        user_id = user.id
    rows, total = order_service.list_orders(
        db,
        user_id=user_id,
        status=status,
        product_id=product_id,
        offset=offset_for(paging.page, paging.size),
        limit=paging.size,
    )
    items = [OrderOut.model_validate(o) for o in rows]
    return make_page(items, total, paging.page, paging.size)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: DB, user: CurrentUser) -> OrderOut:
    return OrderOut.model_validate(_load_authorized(db, user, order_id))


@router.post("/{order_id}/pay", response_model=OrderOut)
def pay_order(order_id: int, db: DB, user: CurrentUser) -> OrderOut:
    order = _load_authorized(db, user, order_id)
    return OrderOut.model_validate(order_service.pay_order(db, order))


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: int, db: DB, user: CurrentUser, clock: ClockDep) -> OrderOut:
    order = _load_authorized(db, user, order_id)
    return OrderOut.model_validate(order_service.cancel_order(db, order, clock.now()))


@router.post("/{order_id}/fulfill", response_model=OrderOut)
def fulfill_order(order_id: int, db: DB, _admin: AdminUser, clock: ClockDep) -> OrderOut:
    order = order_service.get_order(db, order_id)
    return OrderOut.model_validate(order_service.fulfill_order(db, order, clock.now()))
