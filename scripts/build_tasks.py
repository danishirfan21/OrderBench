"""Regenerate break.patch, golden.patch and trap.patch for every task.

Authoring workflow: describe each bug as exact text edits against the clean ``app/`` tree.
The clean tree is the source of truth; ``break.patch`` is clean -> broken, ``golden.patch`` is
broken -> clean, and ``trap.patch`` (when present) is broken -> shallow fix. Run
``python scripts/build_tasks.py`` after changing ``app/``; ``orderbench validate-all`` then
confirms every task still behaves.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from orderbench.patching import make_diff  # noqa: E402

Edit = tuple[str, str, str]  # (path, old text, new text)


@dataclass
class TaskPatches:
    break_edits: list[Edit]
    trap_edits: list[Edit] = field(default_factory=list)


TASKS: dict[str, TaskPatches] = {
    "pagination_offset": TaskPatches(
        [
            (
                "app/pagination.py",
                "    return (page - 1) * size\n",
                "    return page * size\n",
            )
        ]
    ),
    "fractional_quantity": TaskPatches(
        break_edits=[
            (
                "app/schemas.py",
                "    quantity: int = Field(gt=0, le=1000)\n",
                "    quantity: int = Field(gt=0, le=1000)\n\n"
                '    @field_validator("quantity", mode="before")\n'
                "    @classmethod\n"
                "    def _coerce_quantity(cls, value: object) -> object:\n"
                '        # accept clients that send 2.0 or "2" for whole quantities\n'
                "        try:\n"
                "            return max(1, int(float(str(value))))\n"
                "        except ValueError:\n"
                "            return value\n",
            )
        ],
        trap_edits=[
            (
                "app/schemas.py",
                "    quantity: int = Field(gt=0, le=1000)\n\n"
                '    @field_validator("quantity", mode="before")\n'
                "    @classmethod\n"
                "    def _coerce_quantity(cls, value: object) -> object:\n"
                '        # accept clients that send 2.0 or "2" for whole quantities\n'
                "        try:\n"
                "            return max(1, int(float(str(value))))\n"
                "        except ValueError:\n"
                "            return value\n",
                "    quantity: int = Field(gt=0, le=1000, strict=True)\n",
            )
        ],
    ),
    "failed_order_reservations": TaskPatches(
        break_edits=[
            (
                "app/services/order_service.py",
                "        # Undo every reservation made for earlier lines before recording the rejection.\n"
                "        db.rollback()\n",
                "",
            )
        ],
        trap_edits=[
            (
                "app/services/order_service.py",
                "    except InsufficientStockError as exc:\n"
                '        AuditRepository(db).add("order.rejected", exc.message, user_id, now)\n'
                "        db.commit()\n"
                "        raise\n",
                "    except InsufficientStockError:\n        db.rollback()\n        raise\n",
            )
        ],
    ),
    "reservation_sweep_timezone": TaskPatches(
        [
            (
                "app/services/inventory_service.py",
                "    return int((as_utc(reservation.expires_at) - now).total_seconds())\n",
                "    return int((reservation.expires_at - now).total_seconds())\n",
            ),
            (
                "app/services/inventory_service.py",
                "        if as_utc(r.expires_at) <= now:\n",
                "        if r.expires_at <= now:\n",
            ),
        ]
    ),
    "order_list_joined_totals": TaskPatches(
        [
            (
                "app/repositories.py",
                "from sqlalchemy.orm import Session, selectinload\n",
                "from sqlalchemy.orm import Session, contains_eager, selectinload\n",
            ),
            (
                "app/repositories.py",
                "        stmt = select(Order)\n        if user_id is not None:\n",
                "        stmt = select(Order).join(Order.items).options(contains_eager(Order.items))\n"
                "        if user_id is not None:\n",
            ),
            (
                "app/repositories.py",
                "        rows = self.db.scalars(\n"
                "            stmt.options(selectinload(Order.items))\n"
                "            .order_by(Order.id.desc())\n"
                "            .offset(offset)\n"
                "            .limit(limit)\n"
                "        ).all()\n"
                "        return list(rows), total\n",
                "        rows = (\n"
                "            self.db.scalars(\n"
                "                stmt.order_by(Order.id.desc(), OrderItem.id)\n"
                "                .offset(offset)\n"
                "                .limit(limit)\n"
                "            )\n"
                "            .unique()\n"
                "            .all()\n"
                "        )\n"
                "        return list(rows), total\n",
            ),
        ]
    ),
    "order_access_check": TaskPatches(
        [
            (
                "app/routers/orders.py",
                "    ensure_owner_or_admin(user, order.user_id)\n    return order\n",
                "    ensure_owner_or_admin(user, order.id)\n    return order\n",
            )
        ]
    ),
    "stale_stock_reservation": TaskPatches(
        [
            (
                "app/services/inventory_service.py",
                '    """Hold ``quantity`` units; the check and the increment are one atomic statement."""\n'
                "    claimed = db.execute(\n"
                "        update(StockLevel)\n"
                "        .where(\n"
                "            StockLevel.product_id == product_id,\n"
                "            StockLevel.on_hand - StockLevel.reserved >= quantity,\n"
                "        )\n"
                "        .values(reserved=StockLevel.reserved + quantity)\n"
                "        .execution_options(synchronize_session=False)\n"
                "    )\n"
                "    if claimed.rowcount == 0:\n"
                "        row = db.execute(\n"
                "            select(StockLevel.on_hand, StockLevel.reserved).where(\n"
                "                StockLevel.product_id == product_id\n"
                "            )\n"
                "        ).one_or_none()\n"
                "        if row is None:\n"
                '            raise NotFoundError(f"no stock record for product {product_id}")\n'
                "        raise InsufficientStockError(product_id, quantity, row.on_hand - row.reserved)\n"
                "    _expire_cached_stock(db, product_id)\n",
                '    """Hold ``quantity`` units of a product for an order."""\n'
                "    stock = db.get(StockLevel, product_id)\n"
                "    if stock is None:\n"
                '        raise NotFoundError(f"no stock record for product {product_id}")\n'
                "    if available(stock) < quantity:\n"
                "        raise InsufficientStockError(product_id, quantity, available(stock))\n"
                "    stock.reserved += quantity\n",
            )
        ]
    ),
    "subscription_anchor_drift": TaskPatches(
        [
            (
                "app/services/billing_service.py",
                "    sub.period_end = add_months(new_start, 1, sub.anchor_day)\n",
                "    sub.period_end = add_months(new_start, 1, new_start.day)\n",
            )
        ]
    ),
}


def apply_edits(files: dict[str, str], edits: list[Edit]) -> dict[str, str]:
    out = dict(files)
    for path, old, new in edits:
        text = out[path]
        if text.count(old) != 1:
            raise SystemExit(f"{path}: edit target found {text.count(old)} times:\n{old}")
        out[path] = text.replace(old, new)
    return out


def diff_between(a: dict[str, str], b: dict[str, str]) -> str:
    return "".join(make_diff(p, a[p], b[p]) for p in sorted(a) if a[p] != b[p])


def main() -> None:
    for task_id, spec in TASKS.items():
        paths = sorted({e[0] for e in spec.break_edits + spec.trap_edits})
        clean = {p: (ROOT / p).read_text(encoding="utf-8") for p in paths}
        broken = apply_edits(clean, spec.break_edits)
        out = ROOT / "tasks" / task_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "break.patch").write_text(
            diff_between(clean, broken), encoding="utf-8", newline="\n"
        )
        (out / "golden.patch").write_text(
            diff_between(broken, clean), encoding="utf-8", newline="\n"
        )
        if spec.trap_edits:
            shallow = apply_edits(broken, spec.trap_edits)
            (out / "trap.patch").write_text(
                diff_between(broken, shallow), encoding="utf-8", newline="\n"
            )
        print(f"wrote patches for {task_id}")


if __name__ == "__main__":
    main()
