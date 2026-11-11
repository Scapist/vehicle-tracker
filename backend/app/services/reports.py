from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.clock import as_local_date
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


def cost_by_year(db: Session, vehicle_ids: list[int]) -> dict[int, dict[str, int]]:
    names = dict(db.execute(select(m.ServiceType.id, m.ServiceType.name)).all())
    years: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rec in db.scalars(select(m.ServiceRecord).where(m.ServiceRecord.vehicle_id.in_(vehicle_ids))):
        for cat, cents in allocate(rec, names).items():
            years[rec.date.year][cat] += cents
    for ts in db.scalars(select(m.TireSet).where(m.TireSet.vehicle_id.in_(vehicle_ids))):
        if ts.cost_cents and ts.purchase_date:
            years[ts.purchase_date.year]["Tires"] += ts.cost_cents
    return {y: dict(c) for y, c in sorted(years.items())}


def report(db: Session, vehicle_id: int | None, year: int | None) -> dict:
    ids = [vehicle_id] if vehicle_id else list(db.scalars(select(m.Vehicle.id)))
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
