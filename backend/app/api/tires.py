from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.clock import today_local
from app.db import get_db
from app.services import odometer, tires, views

router = APIRouter(tags=["tires"])


class MountIn(BaseModel):
    date: Date | None = None
    km: int | None = None


def get_set(db: Session, set_id: int) -> m.TireSet:
    ts = db.get(m.TireSet, set_id)
    if not ts:
        raise HTTPException(404, "Tire set not found")
    return ts


@router.get("/tire-sets", response_model=list[s.TireSetOut])
def list_tire_sets(vehicle_id: int | None = None, db: Session = Depends(get_db)):
    q = select(m.TireSet).order_by(m.TireSet.retired, m.TireSet.label)
    if vehicle_id is not None:
        q = q.where(m.TireSet.vehicle_id == vehicle_id)
    return [views.tire_out(db, t) for t in db.scalars(q)]


@router.post("/tire-sets", response_model=s.TireSetOut, status_code=201)
def create_tire_set(body: s.TireSetIn, db: Session = Depends(get_db)):
    if not db.get(m.Vehicle, body.vehicle_id):
        raise HTTPException(404, "Vehicle not found")
    ts = m.TireSet(**body.model_dump())
    db.add(ts)
    db.commit()
    return views.tire_out(db, ts)


@router.patch("/tire-sets/{set_id}", response_model=s.TireSetOut)
def patch_tire_set(set_id: int, body: s.TireSetPatch, db: Session = Depends(get_db)):
    ts = get_set(db, set_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k in ("label", "retired"):
            continue
        setattr(ts, k, v)
    db.commit()
    return views.tire_out(db, ts)


@router.post("/tire-sets/{set_id}/mount", response_model=s.TireSetOut)
def mount_set(set_id: int, body: MountIn | None = None, db: Session = Depends(get_db)):
    ts = get_set(db, set_id)
    body = body or MountIn()
    try:
        tires.mount(db, ts, body.date or today_local(), body.km)
    except tires.TireError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return views.tire_out(db, ts)


@router.post("/tire-sets/{set_id}/unmount", response_model=s.TireSetOut)
def unmount_set(set_id: int, body: MountIn | None = None, db: Session = Depends(get_db)):
    ts = get_set(db, set_id)
    body = body or MountIn()
    km = body.km if body.km is not None else odometer.current_km(db, ts.vehicle_id)
    try:
        tires.unmount(db, ts, body.date or today_local(), km)
    except tires.TireError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return views.tire_out(db, ts)


@router.post("/tire-sets/{set_id}/tread", response_model=s.TireSetOut, status_code=201)
def add_tread(set_id: int, body: s.TireTreadIn, db: Session = Depends(get_db)):
    ts = get_set(db, set_id)
    ts.treads.append(m.TireTread(date=body.date or today_local(), depth_mm=body.depth_mm))
    db.commit()
    return views.tire_out(db, ts)
