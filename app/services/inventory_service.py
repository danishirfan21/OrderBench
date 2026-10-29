"""Stock reservation. See DOMAIN.md, section "Inventory"."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import InsufficientStockError, NotFoundError
from app.models import Order, Reservation, StockLevel
from app.repositories import ReservationRepository
from app.timeutil import as_utc


def available(stock: StockLevel) -> int:
    return stock.on_hand - stock.reserved


def reserve(
    db: Session,
    product_id: int,
    quantity: int,
    order_id: int,
    now: datetime,
    ttl_seconds: int,
) -> Reservation:
    """Hold ``quantity`` units; the check and the increment are one atomic statement."""
    claimed = db.execute(
        update(StockLevel)
        .where(
            StockLevel.product_id == product_id,
            StockLevel.on_hand - StockLevel.reserved >= quantity,
        )
        .values(reserved=StockLevel.reserved + quantity)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount == 0:
        row = db.execute(
            select(StockLevel.on_hand, StockLevel.reserved).where(
                StockLevel.product_id == product_id
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError(f"no stock record for product {product_id}")
        raise InsufficientStockError(product_id, quantity, row.on_hand - row.reserved)
    _expire_cached_stock(db, product_id)
    reservation = Reservation(
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        status="active",
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    db.add(reservation)
    db.flush()
    return reservation


def _expire_cached_stock(db: Session, product_id: int) -> None:
    """Atomic UPDATEs bypass the identity map; drop any stale copy of the row."""
    for obj in list(db.identity_map.values()):
        if isinstance(obj, StockLevel) and obj.product_id == product_id:
            db.expire(obj)


def _adjust(db: Session, product_id: int, *, reserved: int = 0, on_hand: int = 0) -> None:
    db.execute(
        update(StockLevel)
        .where(StockLevel.product_id == product_id)
        .values(reserved=StockLevel.reserved + reserved, on_hand=StockLevel.on_hand + on_hand)
        .execution_options(synchronize_session=False)
    )
    _expire_cached_stock(db, product_id)


def release(db: Session, reservation: Reservation, new_status: str) -> None:
    """Return a held reservation to the pool and mark it ``new_status``."""
    if reservation.status not in ("active", "committed"):
        return
    _adjust(db, reservation.product_id, reserved=-reservation.quantity)
    reservation.status = new_status


def consume(db: Session, reservation: Reservation) -> None:
    """Fulfilment: the held units physically leave the warehouse."""
    _adjust(
        db, reservation.product_id, reserved=-reservation.quantity, on_hand=-reservation.quantity
    )
    reservation.status = "consumed"


def seconds_remaining(reservation: Reservation, now: datetime) -> int:
    return int((as_utc(reservation.expires_at) - now).total_seconds())


def active_reservations(db: Session, now: datetime) -> list[tuple[Reservation, int]]:
    out = []
    for r in ReservationRepository(db).with_status("active"):
        remaining = seconds_remaining(r, now)
        if remaining > 0:
            out.append((r, remaining))
    return out


def expire_reservations(db: Session, now: datetime) -> int:
    """Release every active reservation whose expiry has passed. Returns the count."""
    count = 0
    for r in ReservationRepository(db).with_status("active"):
        if as_utc(r.expires_at) <= now:
            release(db, r, "expired")
            count += 1
    if count:
        _expire_orders(db)
    db.commit()
    return count


def _expire_orders(db: Session) -> None:
    db.flush()
    pending = db.scalars(select(Order).where(Order.status == "pending")).all()
    for order in pending:
        if order.reservations and all(r.status == "expired" for r in order.reservations):
            order.status = "expired"
