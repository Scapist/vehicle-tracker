from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.clock import as_local_date, today_local
from app.domain import recurring
from app.services import odometer


def allocate(rec: m.ServiceRecord, names: dict[int, str]) -> dict[str, int]:
    """Split a visit's cost by service type. A lone unpriced item takes the remainder; otherwise
    unallocated cost is reported as 'General'."""
    out: dict[str, int] = defaultdict(int)
    allocated = 0
    for i in rec.items:
        if i.cost_cents is not None:
            out[names[i.service_type_id]] += i.cost_cents
            allocated += i.cost_cents
    remainder = rec.cost_cents - allocated
    unpriced = [i for i in rec.items if i.cost_cents is None]
    if len(unpriced) == 1:
        out[names[unpriced[0].service_type_id]] += remainder
        remainder = 0
    if remainder > 0:
        out["General"] += remainder
    return {k: v for k, v in out.items() if v}


def km_by_year(db: Session, vehicle_id: int) -> dict[int, int]:
    last: dict[int, int] = {}
    first: dict[int, int] = {}
    for r in odometer.valid_readings(db, vehicle_id):
        y = as_local_date(r.recorded_at).year
        first.setdefault(y, r.km)
        last[y] = r.km
    out = {}
    for y in sorted(last):
        start = last.get(y - 1, first[y])
        out[y] = last[y] - start
    return out


@dataclass
class Entry:
    date: date
    vehicle_id: int
    category: str
    cents: int
    source: str  # service | tire | recurring
    label: str
    ref_id: int
    scheduled: bool = False  # a recurring payment that hasn't happened yet


def cost_entries(db: Session, vehicle_ids: list[int], lo: date | None = None, hi: date | None = None,
                 today: date | None = None) -> list[Entry]:
    """Every cost for these vehicles, one entry per category, oldest first. Recurring payments up to today
    count as spent; later ones in [lo, hi] come back as scheduled. Without hi, recurring payments stop at
    today (they never end on their own) and other costs aren't cut off."""
    today = today or today_local()
    lo = lo or date.min
    rec_hi = hi or today
    hi = hi or date.max
    names = dict(db.execute(select(m.ServiceType.id, m.ServiceType.name)).all())
    out: list[Entry] = []
    q = select(m.ServiceRecord).where(m.ServiceRecord.vehicle_id.in_(vehicle_ids),
                                      m.ServiceRecord.date >= lo, m.ServiceRecord.date <= hi)
    for rec in db.scalars(q):
        label = rec.vendor or ", ".join(names[i.service_type_id] for i in rec.items) or "Service"
        for cat, cents in allocate(rec, names).items():
            out.append(Entry(rec.date, rec.vehicle_id, cat, cents, "service", label, rec.id))
    for ts in db.scalars(select(m.TireSet).where(m.TireSet.vehicle_id.in_(vehicle_ids))):
        if ts.cost_cents and ts.purchase_date and lo <= ts.purchase_date <= hi:
            out.append(Entry(ts.purchase_date, ts.vehicle_id, "Tires", ts.cost_cents, "tire", ts.label, ts.id))
    for rc in db.scalars(select(m.RecurringCost).where(m.RecurringCost.vehicle_id.in_(vehicle_ids))):
        if rc.start_date > rec_hi or (rc.end_date and rc.end_date < lo):
            continue
        for d in recurring.occurrences(rc.start_date, rc.every_months, rc.end_date, max(lo, rc.start_date), rec_hi):
            out.append(Entry(d, rc.vehicle_id, rc.category, rc.amount_cents, "recurring", rc.name, rc.id,
                             scheduled=d > today))
    out.sort(key=lambda e: (e.date, e.source, e.ref_id))
    return out


def cost_by_year(db: Session, vehicle_ids: list[int]) -> dict[int, dict[str, int]]:
    years: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in cost_entries(db, vehicle_ids):
        years[e.date.year][e.category] += e.cents
    return {y: dict(c) for y, c in sorted(years.items())}


def _months(lo: date, hi: date) -> list[str]:
    out = []
    y, mo = lo.year, lo.month
    while (y, mo) <= (hi.year, hi.month):
        out.append(f"{y:04d}-{mo:02d}")
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return out


def spending(db: Session, vehicle_ids: list[int], lo: date, hi: date, categories: list[str] | None = None,
             today: date | None = None) -> dict:
    """Spending in [lo, hi] (inclusive), optionally only some categories, with a month-by-month split.
    Totals only count what has happened; recurring payments still to come are reported separately."""
    today = today or today_local()
    entries = cost_entries(db, vehicle_ids, lo, hi, today)
    available = sorted({e.category for e in entries})
    if categories:
        wanted = set(categories)
        entries = [e for e in entries if e.category in wanted]
    spent = [e for e in entries if not e.scheduled]
    months = {k: {"month": k, "total_cents": 0, "by_category": defaultdict(int)} for k in _months(lo, hi)}
    by_cat: dict[str, int] = defaultdict(int)
    for e in spent:
        row = months[f"{e.date.year:04d}-{e.date.month:02d}"]
        row["total_cents"] += e.cents
        row["by_category"][e.category] += e.cents
        by_cat[e.category] += e.cents
    return {
        "total_cents": sum(by_cat.values()),
        "scheduled_cents": sum(e.cents for e in entries if e.scheduled),
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        "by_month": [{**r, "by_category": dict(r["by_category"])} for r in months.values()],
        "entries": [asdict(e) for e in reversed(entries)],
        "categories": available,
    }


def report(db: Session, vehicle_ids: list[int], year: int | None) -> dict:
    ids = vehicle_ids
    costs = cost_by_year(db, ids)
    kms: dict[int, int] = defaultdict(int)
    for vid in ids:
        for y, k in km_by_year(db, vid).items():
            kms[y] += k
    years = sorted(set(costs) | set(kms))
    if year:
        years = [y for y in years if y == year]
    rows = []
    for y in years:
        total = sum(costs.get(y, {}).values())
        km = kms.get(y, 0)
        rows.append({"year": y, "total_cents": total, "by_category": costs.get(y, {}), "km": km,
                     "cost_per_km_cents": round(total / km, 2) if km > 0 else None})
    cats = sorted({c for r in rows for c in r["by_category"]})
    return {"years": rows, "categories": cats}
