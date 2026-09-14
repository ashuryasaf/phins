"""Invoice due-date schedule (pure date arithmetic).

Resolves PHINS_PLATFORM_ASSESSMENT.md D3: ``auto_generate_invoice`` had two
competing quarter-rollover paths in one function. There is now exactly one
answer per frequency, each an explicit helper over ``datetime.date`` so the
edges (Dec 31 → Jan 1, leap day) are unit-testable without a clock.

Semantics are unchanged from the controller for ``monthly`` (first day of
the current month) and ``annual`` (Jan 1 of the current year); ``quarterly``
is the first day of the *next* calendar quarter, rolling the year over from
Q4 to Q1.
"""

from datetime import date, datetime
from typing import Optional, Union

QUARTER_START_MONTHS = (1, 4, 7, 10)

DateLike = Union[date, datetime]


def _as_date(value: Optional[DateLike]) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    return value


def quarter_of(value: DateLike) -> int:
    """1-based calendar quarter (Jan–Mar = 1 … Oct–Dec = 4)."""
    return (_as_date(value).month - 1) // 3 + 1


def current_quarter_start(value: Optional[DateLike] = None) -> date:
    d = _as_date(value)
    return date(d.year, QUARTER_START_MONTHS[quarter_of(d) - 1], 1)


def next_quarter_start(value: Optional[DateLike] = None) -> date:
    """First day of the calendar quarter after the one containing ``value``.

    Oct–Dec rolls to Jan 1 of the following year; every other quarter stays
    in the same year. Day-of-month (incl. Feb 29) never affects the result.
    """
    d = _as_date(value)
    q = quarter_of(d)
    if q == 4:
        return date(d.year + 1, 1, 1)
    return date(d.year, QUARTER_START_MONTHS[q], 1)


def current_month_start(value: Optional[DateLike] = None) -> date:
    d = _as_date(value)
    return date(d.year, d.month, 1)


def current_year_start(value: Optional[DateLike] = None) -> date:
    return date(_as_date(value).year, 1, 1)


def invoice_due_date(billing_frequency: str, value: Optional[DateLike] = None) -> date:
    """Due date for a premium invoice generated on ``value`` (default today)."""
    frequency = str(billing_frequency or '').strip().lower()
    if frequency == 'monthly':
        return current_month_start(value)
    if frequency == 'quarterly':
        return next_quarter_start(value)
    return current_year_start(value)


__all__ = [
    'QUARTER_START_MONTHS', 'quarter_of', 'current_quarter_start', 'next_quarter_start',
    'current_month_start', 'current_year_start', 'invoice_due_date',
]
