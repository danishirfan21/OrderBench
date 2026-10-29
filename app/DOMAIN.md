# Domain rules

The reference service is a small order and inventory backend with subscription billing.
Task statements refer to these rules by id. Money is always integer cents. All instants are
UTC; the service never reads the OS clock directly (see `app/clock.py`).

## Accounts and access

- **A-1** Passwords are stored as salted scrypt hashes; the plain text is never persisted or returned.
- **A-2** Login failures for an unknown email and a wrong password are indistinguishable.
- **A-3** Bearer tokens expire `token_ttl_seconds` after issue, judged against the injected clock.
- **A-4** Roles are `customer` and `admin`. A customer may read and act on only their own orders and
  subscriptions; an admin may act on any. Admin-only: product/plan creation, stock edits, fulfilment,
  the audit log, and the reservation admin endpoints.

## Catalogue

- **C-1** SKUs are upper-cased and trimmed, and unique.
- **C-2** Every product has exactly one stock row: `on_hand` units physically present and
  `reserved` units promised to open orders. `available = on_hand - reserved`.
- **C-3** `on_hand` may never be set below `reserved`.

## Pagination

- **P-1** List endpoints take `page` (1-indexed, default 1) and `size` (1..100, default 20) and return
  `{items, total, page, size, pages}`.
- **P-2** Page 1 holds the first `size` rows of the ordering, page 2 the next `size`, and so on.
  `total` is the number of matching *records*, never the number of joined rows.
- **P-3** A page beyond the last returns no items but still reports `total`.

## Orders

- **O-1** An order has one line per distinct product; repeated products in a request are merged.
- **O-2** Quantities are whole units from 1 to 1000. Numeric strings (`"3"`) and integral floats
  (`3.0`) are accepted as that integer. A fractional (`2.5`), zero, negative, or non-numeric quantity
  is rejected with 422; it is never rounded, truncated or clamped into a valid one.
- **O-3** Placing an order is all-or-nothing. If any line cannot be reserved, no stock is held for any
  other line, no order row remains, and the API answers 409 `insufficient_stock`. The rejection is
  recorded in the audit log as `order.rejected`.
- **O-4** Lifecycle: `pending -> paid -> fulfilled`; `pending|paid -> cancelled`;
  `pending -> expired`. Anything else is a 409.
- **O-5** Order listings are newest first. Customers see only their own orders.
- **O-6** A confirmation is queued after the response is sent (`order.notification_queued` audit row).

## Inventory

- **I-1** Placing an order reserves each line for `reservation_ttl_seconds` (default 900).
- **I-2** Reserving is a check-and-increment against the *current* committed stock; two concurrent
  buyers must never be promised more than `available`.
- **I-3** Paying commits the reservations (no expiry). Cancelling releases them. Fulfilment consumes
  them: both `on_hand` and `reserved` drop by the quantity.
- **I-4** A sweep expires every active reservation whose `expires_at <= now`, returns its units to
  the pool, and marks an order `expired` when all its reservations expired. A reservation is active
  while `expires_at > now`; the admin listing reports `seconds_remaining`.

## Billing

- **B-1** A subscription bills a plan's `monthly_price_cents` per period. The period starts at
  subscribe time; its *anchor day* is that start's day of month.
- **B-2** Each period ends on the anchor day of the next month at the same time of day, clamped to
  the month's length (anchor 31: Feb 28/29, Apr 30, Mar 31...). The anchor never changes, so a
  clamped month does not shift later periods.
- **B-3** Renewal is allowed once `now >= period_end`; the next period starts exactly at the old end.
- **B-4** Changing plan mid-period creates a `proration` invoice for
  `round_half_up((new_price - old_price) * remaining / period_length)`, where both lengths are
  measured in seconds over the *actual* current period, and the single net amount is rounded once.
  Negative amounts are credits. Changes at or after `period_end` are rejected.
