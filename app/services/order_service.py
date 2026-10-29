"""Order lifecycle. See DOMAIN.md, section "Orders"."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.errors import ConflictError, InsufficientStockError, NotFoundError
from app.models import Order, OrderItem, User
from app.repositories import (
    AuditRepository,
    OrderRepository,
    ProductRepository,
    ReservationRepository,
)
from app.schemas import OrderItemIn
from app.services import inventory_service


def _merge_lines(items: list[OrderItemIn]) -> list[tuple[int, int]]:
    """Collapse repeated products into one line, preserving first-seen order."""
    merged: dict[int, int] = {}
    for item in items:
        merged[item.product_id] = merged.get(item.product_id, 0) + item.quantity
    return list(merged.items())


def place_order(
    db: Session,
    user: User,
    items: list[OrderItemIn],
    now: datetime,
    reservation_ttl_seconds: int,
) -> Order:
    user_id = user.id
    lines = _merge_lines(items)
    products = ProductRepository(db).get_many([pid for pid, _ in lines])
    for pid, _ in lines:
        product = products.get(pid)
        if product is None or not product.active:
            raise NotFoundError(f"product {pid} not found")

    order = Order(user_id=user_id, status="pending", total_cents=0, created_at=now)
    db.add(order)
    db.flush()
    try:
        total = 0
        for pid, qty in lines:
            inventory_service.reserve(db, pid, qty, order.id, now, reservation_ttl_seconds)
            price = products[pid].price_cents
            order.items.append(OrderItem(product_id=pid, quantity=qty, unit_price_cents=price))
            total += price * qty
        order.total_cents = total
        db.commit()
    except InsufficientStockError as exc:
        # Undo every reservation made for earlier lines before recording the rejection.
        db.rollback()
        AuditRepository(db).add("order.rejected", exc.message, user_id, now)
        db.commit()
        raise
    return order


def get_order(db: Session, order_id: int) -> Order:
    order = OrderRepository(db).get(order_id)
    if order is None:
        raise NotFoundError(f"order {order_id} not found")
    return order


def list_orders(
    db: Session,
    *,
    user_id: int | None,
    status: str | None,
    product_id: int | None,
    offset: int,
    limit: int,
) -> tuple[list[Order], int]:
    return OrderRepository(db).list(
        user_id=user_id, status=status, product_id=product_id, offset=offset, limit=limit
    )


def pay_order(db: Session, order: Order) -> Order:
    if order.status != "pending":
        raise ConflictError(f"order is {order.status}, only pending orders can be paid")
    for r in ReservationRepository(db).for_order(order.id, "active"):
        r.status = "committed"
    order.status = "paid"
    db.commit()
    return order


def cancel_order(db: Session, order: Order, now: datetime) -> Order:
    if order.status not in ("pending", "paid"):
        raise ConflictError(f"order is {order.status} and cannot be cancelled")
    for r in ReservationRepository(db).for_order(order.id):
        inventory_service.release(db, r, "released")
    order.status = "cancelled"
    AuditRepository(db).add("order.cancelled", f"order {order.id}", order.user_id, now)
    db.commit()
    return order


def fulfill_order(db: Session, order: Order, now: datetime) -> Order:
    if order.status != "paid":
        raise ConflictError(f"order is {order.status}, only paid orders can be fulfilled")
    for r in ReservationRepository(db).for_order(order.id, "committed"):
        inventory_service.consume(db, r)
    order.status = "fulfilled"
    AuditRepository(db).add("order.fulfilled", f"order {order.id}", order.user_id, now)
    db.commit()
    return order
