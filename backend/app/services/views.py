"""Builders that turn ORM rows into API view models."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.domain.due import km_per_day
from app.domain.status import ORDER
from app.services import odometer, records, tires
from app.services.status import StatusItem, vehicle_items


def status_out(i: StatusItem) -> s.StatusItemOut:
    return s.StatusItemOut(subject=i.subject, kind=i.kind, id=i.id, vehicle_id=i.vehicle_id, title=i.title,
                           status=i.status, detail=i.detail, progress=i.progress, due=i.due,
                           informational=i.informational)


def vehicle_out(db: Session, v: m.Vehicle, today: date) -> s.VehicleOut:
    out = s.VehicleOut.model_validate(v)
    out.current_km = odometer.current_km(db, v.id)
    items = [i for i in vehicle_items(db, v.id, today) if not i.informational]
    out.worst_status = min((i.status for i in items), key=lambda x: ORDER[x], default="ok")
    return out


def service_out(db: Session, rec: m.ServiceRecord) -> s.ServiceOut:
    out = s.ServiceOut.model_validate(rec)
    out.type_names = records.type_names(db, rec)
    return out


def tire_out(db: Session, ts: m.TireSet) -> s.TireSetOut:
    out = s.TireSetOut.model_validate(ts)
    out.total_km = tires.total_km(ts, odometer.current_km(db, ts.vehicle_id))
    out.mounted = tires.is_mounted(ts)
    out.latest_tread_mm = tires.latest_tread(ts)
    out.tread_warning = out.latest_tread_mm is not None and out.latest_tread_mm <= tires.tread_threshold(ts.season)
    return out


def dashboard(db: Session, v: m.Vehicle, today: date) -> s.DashboardOut:
    recent = db.scalars(select(m.ServiceRecord).where(m.ServiceRecord.vehicle_id == v.id)
                        .order_by(m.ServiceRecord.date.desc(), m.ServiceRecord.id.desc()).limit(8)).all()
    year_cost = sum(r.cost_cents for r in db.scalars(
        select(m.ServiceRecord).where(m.ServiceRecord.vehicle_id == v.id,
                                      m.ServiceRecord.date >= date(today.year, 1, 1))))
    mounted = tires.mounted_set(db, v.id)
    return s.DashboardOut(
        vehicle=vehicle_out(db, v, today),
        km_per_day=km_per_day(odometer.domain_readings(db, v.id), today),
        items=[status_out(i) for i in vehicle_items(db, v.id, today)],
        recent_services=[service_out(db, r) for r in recent],
        year_cost_cents=year_cost, year=today.year,
        mounted_tire_set=tire_out(db, mounted) if mounted else None)
