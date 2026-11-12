"""When repeating payments fall. Pure: no database, no clock."""
from datetime import date

from app.domain.due import add_months


def occurrences(start: date, every_months: int, end: date | None, lo: date, hi: date) -> list[date]:
    """Payment dates within [lo, hi]. Each one is computed from start (not from the previous one), so a
    payment on the 31st lands on Feb 28 and then back on Mar 31."""
    if every_months < 1:
        return []
    last = min(hi, end) if end else hi
    out = []
    k = 0
    if lo > start:  # skip ahead instead of walking every month since start
        months = (lo.year - start.year) * 12 + lo.month - start.month
        k = max(0, months // every_months - 1)
    while True:
        d = add_months(start, k * every_months)
        if d > last:
            return out
        if d >= lo:
            out.append(d)
        k += 1


def next_occurrence(start: date, every_months: int, end: date | None, today: date) -> date | None:
    """The first payment on or after today, or None once the payments have ended."""
    hits = occurrences(start, every_months, end, today, add_months(today, every_months))
    return hits[0] if hits else None
