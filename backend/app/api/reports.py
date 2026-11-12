import csv
import io

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.api.deps import owned_vehicle, user_vehicle_ids
from app.auth import current_user
from app import schemas as s
from app.clock import as_local_date, today_local
from app.db import get_db
from app.services import reports as svc

router = APIRouter(tags=["reports"])
# cells a spreadsheet would treat as a formula (tab and CR too: Excel strips them first)
FORMULA_START = ("=", "+", "-", "@", chr(9), chr(13))


class YearRow(BaseModel):
    year: int
    total_cents: int
    by_category: dict[str, int]
    km: int
    cost_per_km_cents: float | None


class ReportOut(BaseModel):
    years: list[YearRow]
    categories: list[str]


@router.get("/reports", response_model=ReportOut)
def get_report(vehicle: int | None = None, year: int | None = None, user: m.User = Depends(current_user),
               db: Session = Depends(get_db)):
    return svc.report(db, _scope(db, user, vehicle), year)


def _range(lo: date | None, hi: date | None) -> tuple[date, date]:
    today = today_local()
    lo = lo or date(today.year, 1, 1)
    hi = hi or date(lo.year, 12, 31)
    if hi < lo:
        raise HTTPException(422, "The end of the range is before its start")
    if (hi.year - lo.year) * 12 + hi.month - lo.month >= 240:
        raise HTTPException(422, "Pick a range of at most 20 years")
    return lo, hi


@router.get("/spending", response_model=s.SpendingOut)
def get_spending(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
                 vehicle: int | None = None, category: list[str] = Query(default_factory=list),
                 user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """What was spent in a date range (default: this year), by month and category. Recurring payments
    still to come in the range are only in scheduled_cents."""
    lo, hi = _range(start, end)
    return svc.spending(db, _scope(db, user, vehicle), lo, hi, category)


def _scope(db: Session, user: m.User, vehicle: int | None) -> list[int]:
    """The vehicle ids a report or export covers: one of yours, or all of yours."""
    if vehicle:
        owned_vehicle(db, user, vehicle)
        return [vehicle]
    return user_vehicle_ids(db, user)


def _csv(name: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    # guard against spreadsheet formula injection from free-text fields
    w.writerows([[("'" + c) if isinstance(c, str) and c.startswith(FORMULA_START) else c for c in r] for r in rows])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export/services.csv")
def export_services(vehicle: int | None = None, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    names = dict(db.execute(select(m.ServiceType.id, m.ServiceType.name)).all())
    vs = {v.id: v.nickname for v in db.scalars(select(m.Vehicle).where(m.Vehicle.user_id == user.id))}
    q = select(m.ServiceRecord).order_by(m.ServiceRecord.date)
    q = q.where(m.ServiceRecord.vehicle_id.in_(_scope(db, user, vehicle)))
    rows = [[vs.get(r.vehicle_id), r.date.isoformat(), r.odometer_km, f"{r.cost_cents / 100:.2f}", r.vendor or "",
             "; ".join(names[i.service_type_id] for i in r.items), r.notes or "", len(r.attachments)]
            for r in db.scalars(q)]
    return _csv("services.csv", ["vehicle", "date", "odometer_km", "cost_cad", "vendor", "work", "notes",
                                 "receipts"], rows)


@router.get("/export/odometer.csv")
def export_odometer(vehicle: int | None = None, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    vs = {v.id: v.nickname for v in db.scalars(select(m.Vehicle).where(m.Vehicle.user_id == user.id))}
    q = select(m.OdometerReading).order_by(m.OdometerReading.recorded_at)
    q = q.where(m.OdometerReading.vehicle_id.in_(_scope(db, user, vehicle)))
    rows = [[vs.get(r.vehicle_id), as_local_date(r.recorded_at).isoformat(), r.km, r.source,
             r.is_correction, r.invalidated] for r in db.scalars(q)]
    return _csv("odometer.csv", ["vehicle", "date", "km", "source", "is_correction", "invalidated"], rows)


@router.get("/export/tires.csv")
def export_tires(vehicle: int | None = None, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    vs = {v.id: v.nickname for v in db.scalars(select(m.Vehicle).where(m.Vehicle.user_id == user.id))}
    q = select(m.TireSet).order_by(m.TireSet.id)
    q = q.where(m.TireSet.vehicle_id.in_(_scope(db, user, vehicle)))
    rows = []
    for t in db.scalars(q):
        for mt in t.mounts or [None]:
            rows.append([vs.get(t.vehicle_id), t.label, t.season, t.size or "", t.brand_model or "",
                         t.dot_code or "", f"{(t.cost_cents or 0) / 100:.2f}",
                         mt.mounted_date.isoformat() if mt else "", mt.mounted_km if mt else "",
                         mt.removed_date.isoformat() if mt and mt.removed_date else "",
                         mt.removed_km if mt and mt.removed_km is not None else ""])
    return _csv("tires.csv", ["vehicle", "label", "season", "size", "brand_model", "dot", "cost_cad",
                              "mounted_date", "mounted_km", "removed_date", "removed_km"], rows)


@router.get("/export/spending.csv")
def export_spending(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
                    vehicle: int | None = None, category: list[str] = Query(default_factory=list),
                    user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    lo, hi = _range(start, end)
    vs = {v.id: v.nickname for v in db.scalars(select(m.Vehicle).where(m.Vehicle.user_id == user.id))}
    data = svc.spending(db, _scope(db, user, vehicle), lo, hi, category)
    rows = [[e["date"].isoformat(), vs.get(e["vehicle_id"]), e["category"], e["label"], e["source"],
             f"{e['cents'] / 100:.2f}", "scheduled" if e["scheduled"] else "paid"]
            for e in reversed(data["entries"])]
    return _csv("spending.csv", ["date", "vehicle", "category", "what", "source", "amount_cad", "status"], rows)
