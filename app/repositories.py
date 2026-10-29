"""Repository layer: all SQL lives here or in the atomic stock statements of services."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditLog,
    Invoice,
    Order,
    OrderItem,
    Plan,
    Product,
    Reservation,
    StockLevel,
    Subscription,
    User,
)


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email.lower()))

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user


class ProductRepository:
    SORTS: ClassVar[dict[str, Any]] = {
        "id": Product.id.asc(),
        "name": Product.name.asc(),
        "price": Product.price_cents.asc(),
        "-price": Product.price_cents.desc(),
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, product_id: int) -> Product | None:
        return self.db.get(Product, product_id)

    def get_by_sku(self, sku: str) -> Product | None:
        return self.db.scalar(select(Product).where(Product.sku == sku))

    def get_many(self, ids: Sequence[int]) -> dict[int, Product]:
        rows = self.db.scalars(select(Product).where(Product.id.in_(ids))).all()
        return {p.id: p for p in rows}

    def add(self, product: Product) -> Product:
        self.db.add(product)
        self.db.flush()
        return product

    def list(
        self,
        *,
        q: str | None,
        active: bool | None,
        min_price: int | None,
        max_price: int | None,
        sort: str,
        offset: int,
        limit: int,
    ) -> tuple[list[Product], int]:
        stmt = select(Product)
        if q:
            stmt = stmt.where(func.lower(Product.name).contains(q.lower()))
        if active is not None:
            stmt = stmt.where(Product.active == active)
        if min_price is not None:
            stmt = stmt.where(Product.price_cents >= min_price)
        if max_price is not None:
            stmt = stmt.where(Product.price_cents <= max_price)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        order = self.SORTS.get(sort, Product.id.asc())
        rows = self.db.scalars(stmt.order_by(order, Product.id).offset(offset).limit(limit)).all()
        return list(rows), total


class StockRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, product_id: int) -> StockLevel | None:
        return self.db.get(StockLevel, product_id)

    def add(self, stock: StockLevel) -> StockLevel:
        self.db.add(stock)
        self.db.flush()
        return stock


class OrderRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, order_id: int) -> Order | None:
        return self.db.scalar(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )

    def list(
        self,
        *,
        user_id: int | None,
        status: str | None,
        product_id: int | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Order], int]:
        stmt = select(Order)
        if user_id is not None:
            stmt = stmt.where(Order.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Order.status == status)
        if product_id is not None:
            stmt = stmt.where(Order.items.any(OrderItem.product_id == product_id))
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(
            stmt.options(selectinload(Order.items))
            .order_by(Order.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return list(rows), total


class ReservationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def for_order(self, order_id: int, status: str | None = None) -> list[Reservation]:
        stmt = select(Reservation).where(Reservation.order_id == order_id)
        if status is not None:
            stmt = stmt.where(Reservation.status == status)
        return list(self.db.scalars(stmt.order_by(Reservation.id)).all())

    def with_status(self, status: str) -> list[Reservation]:
        stmt = select(Reservation).where(Reservation.status == status).order_by(Reservation.id)
        return list(self.db.scalars(stmt).all())


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, event: str, detail: str, user_id: int | None, now: datetime) -> AuditLog:
        row = AuditLog(event=event, detail=detail, user_id=user_id, created_at=now)
        self.db.add(row)
        self.db.flush()
        return row

    def list(self, *, event: str | None, offset: int, limit: int) -> tuple[list[AuditLog], int]:
        stmt = select(AuditLog)
        if event is not None:
            stmt = stmt.where(AuditLog.event == event)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(stmt.order_by(AuditLog.id).offset(offset).limit(limit)).all()
        return list(rows), total


class BillingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_plan(self, plan_id: int) -> Plan | None:
        return self.db.get(Plan, plan_id)

    def list_plans(self) -> list[Plan]:
        return list(self.db.scalars(select(Plan).order_by(Plan.id)).all())

    def add_plan(self, plan: Plan) -> Plan:
        self.db.add(plan)
        self.db.flush()
        return plan

    def get_subscription(self, subscription_id: int) -> Subscription | None:
        return self.db.get(Subscription, subscription_id)

    def add_subscription(self, sub: Subscription) -> Subscription:
        self.db.add(sub)
        self.db.flush()
        return sub

    def add_invoice(self, invoice: Invoice) -> Invoice:
        self.db.add(invoice)
        self.db.flush()
        return invoice
