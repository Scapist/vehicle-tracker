from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models as m
from app.clock import as_local_date, now_utc
from app.domain.due import Reading, check_odometer


class OdometerError(ValueError):
    pass


def valid_readings(db: Session, vehicle_id: int) -> list[m.OdometerReading]:
    return list(db.scalars(
        select(m.OdometerReading)
        .where(m.OdometerReading.vehicle_id == vehicle_id, m.OdometerReading.invalidated.is_(False))
        .order_by(m.OdometerReading.recorded_at, m.OdometerReading.id)))


def current_km(db: Session, vehicle_id: int) -> int | None:
    rs = valid_readings(db, vehicle_id)
    return rs[-1].km if rs else None


def domain_readings(db: Session, vehicle_id: int) -> list[Reading]:
    return [Reading(as_local_date(r.recorded_at), r.km) for r in valid_readings(db, vehicle_id)]


def add_reading(db: Session, vehicle_id: int, km: int, source: str = "ui", is_correction: bool = False,
                recorded_at: datetime | None = None, commit: bool = True) -> m.OdometerReading:
    err = check_odometer(current_km(db, vehicle_id), km, is_correction)
    if err:
        raise OdometerError(err)
    if is_correction:
        db.execute(update(m.OdometerReading)
                   .where(m.OdometerReading.vehicle_id == vehicle_id, m.OdometerReading.km > km)
                   .values(invalidated=True))
    r = m.OdometerReading(vehicle_id=vehicle_id, km=km, source=source, is_correction=is_correction,
                          recorded_at=recorded_at or now_utc())
    db.add(r)
    if commit:
        db.commit()
    else:
        db.flush()
    return r
