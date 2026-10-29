"""Write tasks/<id>/task.yaml for every task.

Statements, difficulty, trap documentation and the choice of pass_to_pass files live here.
Node ids are not typed by hand: they are collected from the real test files so they cannot
drift. Held-out tests whose names appear in ``MOVE_TO_P2P`` pass before the fix as well and so
are recorded as pass_to_pass.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from orderbench.evaluate import clean_checkout  # noqa: E402


@dataclass
class Spec:
    title: str
    difficulty: str
    bug_class: str
    statement: str
    p2p_files: list[str]
    timeout: int = 120
    move_to_p2p: list[str] = field(default_factory=list)
    trap: dict[str, str] | None = None


SPECS: dict[str, Spec] = {
    "pagination_offset": Spec(
        title="First page of listings is missing its first records",
        difficulty="easy",
        bug_class="off-by-one in pagination offset",
        statement="""\
Support ticket #4471, from the storefront team:

"Our catalogue page shows the wrong products. We have 50 products and the page size is 10.
Page 1 starts at 'Item 011' instead of at the first product, and the last page (page 5)
comes back empty even though the response says `pages: 5`. When we walk through all the pages
we only ever see 40 of the 50 products. The same thing happens on the 'My orders' screen: the
newest orders are never shown on the first page."

Expected behaviour is in the pagination rules of the domain notes: page 1 holds the first
`size` rows of the ordering. Please fix.
""",
        p2p_files=[
            "tests/test_pagination.py",
            "tests/test_products.py",
            "tests/test_orders.py",
            "tests/test_auth.py",
        ],
    ),
    "fractional_quantity": Spec(
        title="Order quantities like 2.5 or 0 are silently accepted",
        difficulty="easy",
        bug_class="validator silently coerces instead of rejecting",
        statement="""\
A partner integration reported that they ordered "2.5" units of a widget and our API happily
answered 201. The resulting order contains exactly 2 units, and they were billed for 2. A
different partner sent quantity 0 by mistake (a bug in their cart) and got an order for 1 unit,
which they then had to cancel. We would much rather they got an error telling them their
payload is wrong; domain rule O-2 says that fractional, zero and negative quantities must be
rejected, not repaired.

Note that we do have integrations that send whole numbers as strings ("3") or as JSON floats
(3.0), and those must keep working.
""",
        p2p_files=["tests/test_orders.py", "tests/test_pagination.py"],
        trap={
            "description": (
                "Delete the permissive before-validator and mark the quantity field `strict=True`. "
                "That rejects 2.5, 0 and negative values, so every fail_to_pass test goes green."
            ),
            "why_it_fails": (
                'Strict mode also rejects the numeric string "3" and the integral float 3.0, which '
                "rule O-2 requires the API to keep accepting. The visible-suite tests "
                "`test_numeric_quantities_are_accepted[...]` (pass_to_pass) fail, so the shallow "
                "fix is not resolved."
            ),
        },
    ),
    "failed_order_reservations": Spec(
        title="Stock stays reserved after an order is rejected",
        difficulty="medium",
        bug_class="missing rollback on a failure path",
        statement="""\
Ops noticed that available stock keeps shrinking even though nothing is selling. Digging in, it
happens when a customer's cart contains several products and one of them is out of stock: the
customer correctly gets a 409 insufficient_stock error, but the other items in that cart stay
reserved. Our dashboard shows reserved units with no matching order lines, an order row with
no items sitting in `pending`, and a few popular items now appear sold out although the
warehouse is full.

Rule O-3 says a rejected order must be all-or-nothing. A rejected order must still show up in
the audit log, as it does today.
""",
        p2p_files=["tests/test_orders.py", "tests/test_inventory.py", "tests/test_products.py"],
        trap={
            "description": (
                "Roll back and re-raise, and drop the code that records the rejection in the "
                "audit log (it is the audit commit that appears to be 'persisting the "
                "reservations')."
            ),
            "why_it_fails": (
                "The stock and order rows are restored, so the new tests pass, but rule O-3 (and the "
                "ticket) require rejections to stay in the audit log. `test_rejected_order_is_audited` "
                "(pass_to_pass) fails. The correct fix keeps the audit write but performs it after the "
                "rollback."
            ),
        },
    ),
    "reservation_sweep_timezone": Spec(
        title="Reservation sweep and active-reservation view return 500",
        difficulty="medium",
        bug_class="timezone-naive datetime compared with aware datetime",
        statement="""\
Since we went live, the nightly job that releases abandoned carts has been failing, and so has
the admin "active reservations" screen. Both answer with a 500 as soon as at least one
reservation exists (an empty database is fine, which is why staging looked healthy). The server
log has a TypeError about comparing or subtracting datetimes, but only on reservations read
back from the database, never on ones created in the same request. Because the sweep never runs,
abandoned carts hold stock forever (rule I-4).

Reservations should expire exactly at their deadline, and the admin screen should show the
whole seconds remaining.
""",
        p2p_files=["tests/test_inventory.py", "tests/test_orders.py", "tests/test_billing.py"],
        move_to_p2p=["test_committed_reservations_survive_the_sweep"],
    ),
    "order_list_joined_totals": Spec(
        title="Order list totals and page sizes are wrong for multi-item orders",
        difficulty="medium",
        bug_class="N+1 'optimisation' (join) that breaks pagination assumptions",
        statement="""\
After last sprint's performance work on the orders screen (we were seeing one extra query per
order), customers with big baskets see strange things: a customer with 3 orders of 3 items each
gets `total: 9` and `pages: 5` with a page size of 2, the first page shows only one order, and
orders appear to be missing between pages. Filtering by product shows the same inflation. The
numbers are right for customers whose orders all contain a single item.

Rule P-2: `total` counts matching orders, and each page holds `size` orders. We still don't
want the per-order query back.
""",
        p2p_files=["tests/test_orders.py", "tests/test_pagination.py", "tests/test_products.py"],
    ),
    "order_access_check": Spec(
        title="Customers can read and cancel other customers' orders",
        difficulty="medium",
        bug_class="authorization check applied to the wrong object",
        statement="""\
Security review finding: logged in as a regular customer I could open somebody else's order by
guessing ids. I tried it on staging with two accounts. My second account could `GET`, pay and
cancel an order that belonged to the first account, but only for some order numbers; for most
numbers I correctly got a 403. Meanwhile, the first account sometimes got a 403 on its *own*
orders. The order-ownership rule is A-4. Whatever the cause, it's in our access check and
affects every order endpoint that is limited to the owner.
""",
        p2p_files=[
            "tests/test_orders.py",
            "tests/test_billing.py",
            "tests/test_auth.py",
            "tests/test_products.py",
        ],
        move_to_p2p=["test_admin_reads_everything"],
    ),
    "stale_stock_reservation": Spec(
        title="Oversold the last units during a flash sale",
        difficulty="hard",
        bug_class="race (stale read / lost update) in reservation logic",
        statement="""\
During Friday's flash sale we sold more units of some items than we had. Example: 5 gadgets
on hand, two customers checked out within a few milliseconds of each other for 4 gadgets each,
and both orders were accepted. Afterwards the stock screen said 4 gadgets were reserved, not 8,
so nothing flagged it until fulfilment ran out. A related symptom: two smaller concurrent
orders (2 + 2) left the reserved counter at 2, so later customers could still buy units that
were already promised.

We cannot reproduce it with one request at a time, and it only happens when requests overlap.
Rule I-2 is the requirement: two concurrent buyers must never be promised more than is
available, and no reservation may be lost. Stock changes still need to be committed per order.
""",
        p2p_files=["tests/test_inventory.py", "tests/test_orders.py", "tests/test_products.py"],
        timeout=180,
    ),
    "subscription_anchor_drift": Spec(
        title="Customers billed on the 31st drift to the 28th and are prorated wrongly",
        difficulty="hard",
        bug_class="proration / period arithmetic error at a month boundary",
        statement="""\
Finance flagged a pattern in subscription invoices. Customers who subscribed on the 31st (or the
30th, or 29th) are renewed correctly in February, clamped to the 28th (or 29th in a leap year),
but they are then renewed on the 28th in March, April and every month after that, instead of
going back to the 31st. Their periods are shorter than they should be, so mid-period plan
upgrades are being prorated against the wrong number of days: one customer on a 3000-cent plan
upgrading to a 6000-cent plan on March 16 was charged a proration of 1286 cents, but the 31-day
March period (Feb 28 to Mar 31) puts the right charge at 1452.

Rule B-2 says the anchor day never changes. Customers who subscribed on days 1-28 are fine.
""",
        p2p_files=["tests/test_billing.py", "tests/test_auth.py", "tests/test_security.py"],
        timeout=180,
    ),
}


def collect(workspace: Path, targets: list[str]) -> list[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-c", "pytest.ini", *targets],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={
            "PYTHONPATH": str(workspace),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "SYSTEMROOT": "C:\\Windows",
        },
    )
    return [line.strip() for line in proc.stdout.splitlines() if "::" in line]


def main() -> None:
    for task_id, spec in SPECS.items():
        task_dir = ROOT / "tasks" / task_id
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            clean_checkout(ROOT, ws)
            held = ws / "tests" / "held_out" / task_id
            held.mkdir(parents=True)
            for src in (task_dir / "tests").glob("test_*.py"):
                (held / src.name).write_bytes(src.read_bytes())
            held_ids = collect(ws, [f"tests/held_out/{task_id}"])
            p2p = collect(ws, spec.p2p_files)
        moved = [i for i in held_ids if i.split("::")[1].split("[")[0] in spec.move_to_p2p]
        f2p = [i for i in held_ids if i not in moved]
        doc: dict[str, object] = {
            "id": task_id,
            "title": spec.title,
            "difficulty": spec.difficulty,
            "bug_class": spec.bug_class,
            "statement": spec.statement,
            "fail_to_pass": f2p,
            "pass_to_pass": sorted(set(p2p + moved)),
            "timeout_seconds": spec.timeout,
        }
        if spec.trap:
            doc["trap"] = {"shallow_patch": "trap.patch", **spec.trap}
        text = yaml.safe_dump(doc, sort_keys=False, width=100, allow_unicode=True)
        (task_dir / "task.yaml").write_text(text, encoding="utf-8", newline="\n")
        print(f"{task_id}: {len(f2p)} fail_to_pass, {len(doc['pass_to_pass'])} pass_to_pass")  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
