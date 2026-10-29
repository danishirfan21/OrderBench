"""Datetime helpers.

SQLite hands back naive datetimes even for ``DateTime(timezone=True)`` columns,
so values read from the database must be normalised before they are compared
with the (aware) clock.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def add_months(value: datetime, months: int, anchor_day: int) -> datetime:
    """Move ``value`` forward by whole months, landing on ``anchor_day``.

    The day is clamped to the length of the target month, so an anchor of 31
    yields Feb 28/29, Apr 30, and so on.
    """
    index = value.year * 12 + (value.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
