"""Background work. Runs after the response is sent, in its own session."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.clock import Clock
from app.repositories import AuditRepository


def notify_order_placed(
    session_factory: sessionmaker[Session], clock: Clock, order_id: int, user_id: int
) -> None:
    """Stand-in for sending a confirmation email: records that one was queued."""
    with session_factory() as db:
        AuditRepository(db).add(
            "order.notification_queued", f"order {order_id}", user_id, clock.now()
        )
        db.commit()
