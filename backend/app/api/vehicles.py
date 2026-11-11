from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.clock import now_utc, today_local, tz
from app.db import get_db
from app.services import evaluator_hook, odometer, views

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def get_vehicle(db: Session, vehicle_id: int) -> m.Vehicle:
    v = db.get(m.Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, "Vehicle not found")
    return v


@router.get("", response_model=list[s.VehicleOut])
def list_vehicles(include_archived: bool = False, db: Session = Depends(get_db)):
    q = select(m.Vehicle).order_by(m.Vehicle.nickname)
    if not include_archived:
        q = q.where(m.Vehicle.archived.is_(False))
    today = today_local()
    return [views.vehicle_out(db, v, today) for v in db.scalars(q)]


@router.post("", response_model=s.VehicleOut, status_code=201)
def create_vehicle(body: s.VehicleIn, db: Session = Depends(get_db)):
    v = m.Vehicle(**body.model_dump())
    db.add(v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A vehicle with that nickname already exists")
    return views.vehicle_out(db, v, today_local())


@router.get("/{vehicle_id}", response_model=s.VehicleOut)
def read_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    return views.vehicle_out(db, get_vehicle(db, vehicle_id), today_local())


@router.patch("/{vehicle_id}", response_model=s.VehicleOut)
def patch_vehicle(vehicle_id: int, body: s.VehiclePatch, db: Session = Depends(get_db)):
    v = get_vehicle(db, vehicle_id)
    for k, val in body.model_dump(exclude_unset=True).items():
        if val is None and k != "vin":  # only the VIN is nullable
            continue
        setattr(v, k, val)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A vehicle with that nickname already exists")
    return views.vehicle_out(db, v, today_local())


@router.get("/{vehicle_id}/dashboard", response_model=s.DashboardOut)
def vehicle_dashboard(vehicle_id: int, db: Session = Depends(get_db)):
    return views.dashboard(db, get_vehicle(db, vehicle_id), today_local())


@router.get("/{vehicle_id}/odometer", response_model=list[s.OdometerOut])
def odometer_history(vehicle_id: int, db: Session = Depends(get_db)):
    get_vehicle(db, vehicle_id)
    return list(db.scalars(select(m.OdometerReading).where(m.OdometerReading.vehicle_id == vehicle_id)
                           .order_by(m.OdometerReading.recorded_at.desc(), m.OdometerReading.id.desc())))


@router.post("/{vehicle_id}/odometer", response_model=s.OdometerOut, status_code=201)
def add_odometer(vehicle_id: int, body: s.OdometerIn, db: Session = Depends(get_db)):
    get_vehicle(db, vehicle_id)
    at = now_utc()
    if body.recorded_on and body.recorded_on > today_local():
        raise HTTPException(422, "The date can't be in the future")
    if body.recorded_on and body.recorded_on != today_local():
        at = datetime.combine(body.recorded_on, time(12), tzinfo=tz())
    try:
        r = odometer.add_reading(db, vehicle_id, body.km, "ui", body.is_correction, at)
    except odometer.OdometerError as e:
        raise HTTPException(422, str(e))
    evaluator_hook.after_change(db)
    return r


@router.delete("/{vehicle_id}/odometer/{reading_id}", status_code=204)
def delete_odometer(vehicle_id: int, reading_id: int, db: Session = Depends(get_db)):
    r = db.get(m.OdometerReading, reading_id)
    if not r or r.vehicle_id != vehicle_id:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    evaluator_hook.after_change(db)
