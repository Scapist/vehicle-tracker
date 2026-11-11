from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services import odometer


class TireError(ValueError):
    pass


def total_km(ts: m.TireSet, cur_km: int | None) -> int:
    total = 0
    for mt in ts.mounts:
        end = mt.removed_km if mt.removed_km is not None else cur_km
        if end is not None:
            total += max(0, end - mt.mounted_km)
    return total


def is_mounted(ts: m.TireSet) -> bool:
    return any(mt.removed_date is None for mt in ts.mounts)


def tread_threshold(season: str) -> float:
    return 4.0 if season == "winter" else 3.0


def latest_tread(ts: m.TireSet) -> float | None:
    if not ts.treads:
        return None
    return max(ts.treads, key=lambda t: (t.date, t.id)).depth_mm


def mounted_set(db: Session, vehicle_id: int) -> m.TireSet | None:
    for ts in db.scalars(select(m.TireSet).where(m.TireSet.vehicle_id == vehicle_id)):
        if is_mounted(ts):
            return ts
    return None


def unmount(db: Session, ts: m.TireSet, on: date, km: int | None) -> None:
    open_mounts = [mt for mt in ts.mounts if mt.removed_date is None]
    if not open_mounts:
        raise TireError("That set isn't mounted")
    for mt in open_mounts:
        mt.removed_date = on
        mt.removed_km = max(km if km is not None else mt.mounted_km, mt.mounted_km)


def mount(db: Session, ts: m.TireSet, on: date, km: int | None = None) -> None:
    """Mounts `ts`, taking off whichever set is on the car so only one is ever mounted."""
    if ts.retired:
        raise TireError("That set is retired")
    if is_mounted(ts):
        raise TireError("That set is already mounted")
    km = km if km is not None else (odometer.current_km(db, ts.vehicle_id) or 0)
    other = mounted_set(db, ts.vehicle_id)
    if other:
        unmount(db, other, on, km)
    ts.mounts.append(m.TireMount(mounted_date=on, mounted_km=km))
