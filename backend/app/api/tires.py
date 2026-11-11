from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.api.deps import owned_tire_set, owned_vehicle
from app.auth import current_user
from app.clock import today_local
from app.db import get_db
from app.services import odometer, tires, views

router = APIRouter(tags=["tires"])


class MountIn(BaseModel):
    date: Date | None = None
    km: int | None = None




@router.get("/tire-sets", response_model=list[s.TireSetOut])
def list_tire_sets(vehicle_id: int | None = None, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    q = (select(m.TireSet).join(m.Vehicle, m.Vehicle.id == m.TireSet.vehicle_id)
         .where(m.Vehicle.user_id == user.id).order_by(m.TireSet.retired, m.TireSet.label))
    if vehicle_id is not None:
        q = q.where(m.TireSet.vehicle_id == vehicle_id)
    return [views.tire_out(db, t) for t in db.scalars(q)]


@router.post("/tire-sets", response_model=s.TireSetOut, status_code=201)
def create_tire_set(body: s.TireSetIn, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    owned_vehicle(db, user, body.vehicle_id)
    ts = m.TireSet(**body.model_dump())
    db.add(ts)
    db.commit()
    return views.tire_out(db, ts)


@router.patch("/tire-sets/{set_id}", response_model=s.TireSetOut)
def patch_tire_set(set_id: int, body: s.TireSetPatch, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    ts = owned_tire_set(db, user, set_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k in ("label", "retired"):
            continue
        setattr(ts, k, v)
    db.commit()
    return views.tire_out(db, ts)


@router.post("/tire-sets/{set_id}/mount", response_model=s.TireSetOut)
def mount_set(set_id: int, body: MountIn | None = None, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    ts = owned_tire_set(db, user, set_id)
    body = body or MountIn()
    try:
        tires.mount(db, ts, body.date or today_local(), body.km)
    except tires.TireError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return views.tire_out(db, ts)


@router.post("/tire-sets/{set_id}/unmount", response_model=s.TireSetOut)
def unmount_set(set_id: int, body: MountIn | None = None, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    ts = owned_tire_set(db, user, set_id)
    body = body or MountIn()
    km = body.km if body.km is not None else odometer.current_km(db, ts.vehicle_id)
    try:
        tires.unmount(db, ts, body.date or today_local(), km)
    except tires.TireError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return views.tire_out(db, ts)


@router.post("/tire-sets/{set_id}/tread", response_model=s.TireSetOut, status_code=201)
def add_tread(set_id: int, body: s.TireTreadIn, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    ts = owned_tire_set(db, user, set_id)
    ts.treads.append(m.TireTread(date=body.date or today_local(), depth_mm=body.depth_mm))
    db.commit()
    return views.tire_out(db, ts)
