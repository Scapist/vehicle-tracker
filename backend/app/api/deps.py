"""Ownership checks. Anything that isn't the current user's is reported as not found, never as forbidden,
so ids belonging to other people can't be probed."""
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models as m


def _missing(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")


def find_owned_vehicle(db: Session, user: m.User, vehicle_id: int) -> m.Vehicle | None:
    """The one place that decides whether a vehicle is this user's (API and bot both use it)."""
    v = db.get(m.Vehicle, vehicle_id)
    return v if v and v.user_id == user.id else None


def owned_vehicle(db: Session, user: m.User, vehicle_id: int) -> m.Vehicle:
    v = find_owned_vehicle(db, user, vehicle_id)
    if not v:
        raise _missing("Vehicle")
    return v


def owned_rule(db: Session, user: m.User, rule_id: int) -> m.ReminderRule:
    r = db.get(m.ReminderRule, rule_id)
    if not r:
        raise _missing("Reminder")
    owned_vehicle(db, user, r.vehicle_id)
    return r


def owned_service(db: Session, user: m.User, service_id: int) -> m.ServiceRecord:
    rec = db.get(m.ServiceRecord, service_id)
    if not rec:
        raise _missing("Service")
    owned_vehicle(db, user, rec.vehicle_id)
    return rec


def owned_attachment(db: Session, user: m.User, attachment_id: int) -> m.Attachment:
    att = db.get(m.Attachment, attachment_id)
    if not att:
        raise _missing("Attachment")
    owned_service(db, user, att.service_record_id)
    return att


def owned_tire_set(db: Session, user: m.User, set_id: int) -> m.TireSet:
    ts = db.get(m.TireSet, set_id)
    if not ts:
        raise _missing("Tire set")
    owned_vehicle(db, user, ts.vehicle_id)
    return ts


def owned_date_item(db: Session, user: m.User, item_id: int) -> m.DateItem:
    di = db.get(m.DateItem, item_id)
    if not di or di.user_id != user.id:
        raise _missing("Date")
    return di


def owned_recurring_cost(db: Session, user: m.User, cost_id: int) -> m.RecurringCost:
    rc = db.get(m.RecurringCost, cost_id)
    if not rc or not find_owned_vehicle(db, user, rc.vehicle_id):
        raise _missing("Payment")
    return rc


def visible_service_types(user: m.User):
    """The built-in service types plus the ones this user added."""
    return or_(m.ServiceType.user_id.is_(None), m.ServiceType.user_id == user.id)


def usable_type_ids(db: Session, user: m.User) -> set[int]:
    return set(db.scalars(select(m.ServiceType.id).where(visible_service_types(user))))


def owned_service_type(db: Session, user: m.User, type_id: int) -> m.ServiceType:
    """A custom service type of this user's (the built-ins can't be changed)."""
    t = db.get(m.ServiceType, type_id)
    if not t or t.user_id != user.id:
        raise _missing("Service")
    return t


def user_vehicle_ids(db: Session, user: m.User) -> list[int]:
    return list(db.scalars(select(m.Vehicle.id).where(m.Vehicle.user_id == user.id)))
