"""Plain-language descriptions of due results."""
from datetime import date

from app.domain.due import DUE_SOON, OK, OVERDUE, UNKNOWN, DueResult

ORDER = {OVERDUE: 0, DUE_SOON: 1, UNKNOWN: 2, OK: 3}


def fmt_date(d: date) -> str:
    return f"{d:%b} {d.day}"


def describe(res: DueResult, today: date) -> str:
    if res.status == UNKNOWN:
        return res.reason or "Log when this was last done"
    if res.status == OVERDUE:
        parts = []
        if res.km_remaining is not None and res.km_remaining <= 0:
            parts.append("due now" if res.km_remaining == 0 else f"{-res.km_remaining:,} km over")
        if res.due_date and res.due_date < today:
            n = (today - res.due_date).days
            parts.append(f"{n} day{'s' if n != 1 else ''} overdue")
        return ", ".join(parts) or "overdue"
    parts = []
    if res.km_remaining is not None:
        parts.append(f"~{res.km_remaining:,} km left")
        if res.est_date and (not res.due_date or res.est_date <= res.due_date):
            parts.append(f"about {fmt_date(res.est_date)}")
    if res.due_date and not (res.est_date and res.est_date <= res.due_date):
        n = (res.due_date - today).days
        parts.append(f"due {fmt_date(res.due_date)} ({'today' if n == 0 else f'in {n} days'})")
    text = ", ".join(parts)
    if res.reason and not res.due_date:
        text += f". {res.reason}"
    return text


def describe_date_item(due: date, today: date) -> str:
    n = (due - today).days
    if n < 0:
        return f"{-n} day{'s' if n != -1 else ''} overdue (was {fmt_date(due)})"
    return f"{fmt_date(due)} ({'today' if n == 0 else f'in {n} days'})"
