"""Pure due-date logic. No DB, no clock: callers pass `today`."""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

Date = date

OK, DUE_SOON, OVERDUE, UNKNOWN = "ok", "due_soon", "overdue", "unknown"
RECENT_DAYS = 90
MIN_SPAN_DAYS = 14


@dataclass(frozen=True)
class Rule:
    interval_km: int | None = None
    interval_months: int | None = None
    soon_km: int = 1000
    soon_days: int = 30


@dataclass(frozen=True)
class Anchor:
    """When the thing was last done (a service, or the rule's baseline)."""
    date: Date | None = None
    km: int | None = None


@dataclass(frozen=True)
class Reading:
    date: Date
    km: int


@dataclass(frozen=True)
class DueResult:
    status: str
    due_km: int | None = None
    km_remaining: int | None = None
    due_date: date | None = None  # time-based limit
    est_date: date | None = None  # estimated date the km limit is reached
    effective_date: date | None = None  # earlier of the two
    days_remaining: int | None = None  # to effective_date
    progress: float | None = None  # share of the interval used; >1 means overdue
    reason: str | None = None  # set when status is unknown or no estimate


def add_months(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    year, month = divmod(idx, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def km_per_day(readings: list[Reading], today: date) -> float | None:
    """Average km/day over the last 90 days; falls back to full history."""
    def rate(rs: list[Reading]) -> float | None:
        if len(rs) < 2:
            return None
        rs = sorted(rs, key=lambda r: (r.date, r.km))
        span = (rs[-1].date - rs[0].date).days
        gained = rs[-1].km - rs[0].km
        if span < MIN_SPAN_DAYS or gained <= 0:
            return None
        return gained / span

    recent = [r for r in readings if r.date >= today - timedelta(days=RECENT_DAYS)]
    return rate(recent) or rate(readings)


def compute_due(rule: Rule, anchor: Anchor | None, current_km: int | None,
                readings: list[Reading], today: date) -> DueResult:
    anchor = anchor or Anchor()
    # a zero or negative interval is meaningless (and would divide by zero): treat it as unset
    rule = Rule(rule.interval_km if rule.interval_km and rule.interval_km > 0 else None,
                rule.interval_months if rule.interval_months and rule.interval_months > 0 else None,
                rule.soon_km, rule.soon_days)
    use_km = rule.interval_km is not None and anchor.km is not None and current_km is not None
    use_time = rule.interval_months is not None and anchor.date is not None
    if not (use_km or use_time):
        return DueResult(UNKNOWN, reason="Log when this was last done")

    due_km = km_rem = None
    est = None
    reason = None
    progress: list[float] = []
    if use_km:
        due_km = anchor.km + rule.interval_km
        km_rem = due_km - current_km
        progress.append((current_km - anchor.km) / rule.interval_km)
        rate = km_per_day(readings, today)
        if rate:
            est = today + timedelta(days=max(0, round(km_rem / rate)))
        else:
            reason = "Not enough driving data to estimate a date yet"

    due_date = None
    if use_time:
        due_date = add_months(anchor.date, rule.interval_months)
        total = (due_date - anchor.date).days
        progress.append((today - anchor.date).days / total if total else 1.0)

    dates = [d for d in (due_date, est) if d]
    eff = min(dates) if dates else None
    days_rem = (eff - today).days if eff else None
    time_rem = (due_date - today).days if due_date else None

    overdue = (km_rem is not None and km_rem <= 0) or (time_rem is not None and time_rem < 0)
    soon = (km_rem is not None and km_rem <= rule.soon_km) or (
        time_rem is not None and time_rem <= rule.soon_days)
    status = OVERDUE if overdue else DUE_SOON if soon else OK
    return DueResult(status, due_km, km_rem, due_date, est, eff, days_rem, max(progress), reason)


def check_odometer(latest_km: int | None, new_km: int, is_correction: bool) -> str | None:
    """Return an error message if the reading is not acceptable, else None."""
    if new_km < 0:
        return "Odometer can't be negative"
    if latest_km is not None and new_km < latest_km and not is_correction:
        return f"{new_km:,} km is below the current {latest_km:,} km. Mark it as a correction if that's right"
    return None


def roll_yearly(due: date, today: date) -> date:
    """Next yearly occurrence after marking done: a year on, and never still in the past."""
    nxt = add_months(due, 12)
    while nxt < today:
        nxt = add_months(nxt, 12)
    return nxt
