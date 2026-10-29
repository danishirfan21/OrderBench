from __future__ import annotations

from fastapi import APIRouter

from app.deps import DB, AdminUser, ClockDep, Pagination
from app.pagination import Page, make_page, offset_for
from app.repositories import AuditRepository
from app.schemas import AuditOut, ReservationOut, SweepOut
from app.services import inventory_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/reservations", response_model=list[ReservationOut])
def active_reservations(db: DB, _admin: AdminUser, clock: ClockDep) -> list[ReservationOut]:
    rows = inventory_service.active_reservations(db, clock.now())
    return [
        ReservationOut(
            id=r.id,
            order_id=r.order_id,
            product_id=r.product_id,
            quantity=r.quantity,
            status=r.status,
            expires_at=r.expires_at,
            seconds_remaining=remaining,
        )
        for r, remaining in rows
    ]


@router.post("/reservations/sweep", response_model=SweepOut)
def sweep(db: DB, _admin: AdminUser, clock: ClockDep) -> SweepOut:
    return SweepOut(expired=inventory_service.expire_reservations(db, clock.now()))


@router.get("/audit", response_model=Page[AuditOut])
def audit_log(
    db: DB, _admin: AdminUser, paging: Pagination, event: str | None = None
) -> Page[AuditOut]:
    rows, total = AuditRepository(db).list(
        event=event, offset=offset_for(paging.page, paging.size), limit=paging.size
    )
    return make_page([AuditOut.model_validate(r) for r in rows], total, paging.page, paging.size)
