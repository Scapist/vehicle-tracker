"""Asks for the odometer when a vehicle hasn't had a reading in a while. Km-based reminders are only as good
as the latest reading, so a quiet odometer means "due soon" can arrive late."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.clock import as_local_date, today_local
from app.domain.status import fmt_date
from app.evaluator import alert_address
from app.notify.base import Action
from app.notify.outbox import enqueue
from app.services import odometer


def nudge_round(last: date, today: date, every_days: int) -> int | None:
    """Which nudge is due: 1 after every_days without a reading, 2 after twice that, and so on.
    None when it's too soon or nudging is off."""
    if every_days <= 0:
        return None
    n = (today - last).days // every_days
    return n if n >= 1 else None


def queue_nudges(db: Session, today: date | None = None) -> int:
    """Queue one chat question per quiet vehicle. Returns how many were queued."""
    today = today or today_local()
    queued = 0
    vehicles = db.scalars(select(m.Vehicle).where(m.Vehicle.archived.is_(False), m.Vehicle.user_id.is_not(None),
                                                  m.Vehicle.nudge_days > 0))
    for v in vehicles:
        owner = db.get(m.User, v.user_id)
        if not owner or not alert_address(owner):
            continue  # it's a chat question; without a linked chat app there's nowhere to ask
        has_km_rule = db.scalar(select(m.ReminderRule.id).where(
            m.ReminderRule.vehicle_id == v.id, m.ReminderRule.enabled.is_(True),
            m.ReminderRule.interval_km.is_not(None)).limit(1))
        readings = odometer.valid_readings(db, v.id)
        if not has_km_rule or not readings:
            continue  # nothing depends on the odometer, or no starting point yet
        last = as_local_date(readings[-1].recorded_at)
        n = nudge_round(last, today, v.nudge_days)
        if n is None:
            continue
        days = (today - last).days
        several = db.scalar(select(m.Vehicle.id).where(m.Vehicle.user_id == v.user_id, m.Vehicle.id != v.id,
                                                       m.Vehicle.archived.is_(False)).limit(1))
        example = f"{v.nickname} {readings[-1].km + 1000:,}" if several else f"{readings[-1].km + 1000:,}"
        body = (f"Last reading: {readings[-1].km:,} km on {fmt_date(last)} ({days} days ago).\n"
                f"Reply with the current number, e.g. \"{example}\", to keep the km reminders accurate.")
        queued += enqueue(db, "vehicle-tracker", f"nudge:{v.id}|{last.isoformat()}|{n}",
                          f"{v.nickname}: what's the odometer at?", body,
                          [Action("Stop asking", f"nudge:off:{v.id}")], recipient=f"user:{v.user_id}")
    db.commit()
    return queued
