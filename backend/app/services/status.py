"""Builds status items (rules + date items) for vehicles. Shared by dashboard, evaluator and feed."""
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.domain.due import DUE_SOON, OK, OVERDUE, Anchor, Rule, compute_due
from app.domain.status import ORDER, describe, describe_date_item
from app.services import odometer


log = logging.getLogger("status")


@dataclass
class StatusItem:
    subject: str  # rule:12 | date:5
    kind: str  # rule | date
    id: int
    vehicle_id: int | None
    title: str
    status: str
    detail: str
    progress: float | None
    due: date | None
    cycle_key: str
    informational: bool = False
    km_remaining: int | None = None
    owner_id: int | None = None  # the account the item belongs to (alerts go to them)


def rule_anchor(db: Session, rule: m.ReminderRule) -> Anchor | None:
    last = db.execute(
        select(m.ServiceRecord.date, m.ServiceRecord.odometer_km)
        .join(m.ServiceRecordItem, m.ServiceRecordItem.service_record_id == m.ServiceRecord.id)
        .where(m.ServiceRecord.vehicle_id == rule.vehicle_id,
               m.ServiceRecordItem.service_type_id == rule.service_type_id)
        .order_by(m.ServiceRecord.date.desc(), m.ServiceRecord.id.desc()).limit(1)).first()
    if last:
        return Anchor(last[0], last[1])
    if rule.baseline_date or rule.baseline_km is not None:
        return Anchor(rule.baseline_date, rule.baseline_km)
    return None


def vehicle_items(db: Session, vehicle_id: int, today: date) -> list[StatusItem]:
    cur = odometer.current_km(db, vehicle_id)
    readings = odometer.domain_readings(db, vehicle_id)
    items: list[StatusItem] = []
    rules = db.scalars(select(m.ReminderRule).where(m.ReminderRule.vehicle_id == vehicle_id,
                                                     m.ReminderRule.enabled.is_(True)))
    for rule in rules:
        anchor = rule_anchor(db, rule)
        try:
            res = compute_due(Rule(rule.interval_km, rule.interval_months, rule.soon_km, rule.soon_days),
                              anchor, cur, readings, today)
        except Exception:  # noqa: BLE001 - one broken rule must not take down the dashboard
            log.exception("could not compute rule %s", rule.id)
            continue
        cycle = f"{anchor.date}:{anchor.km}" if anchor else "none"
        items.append(StatusItem(f"rule:{rule.id}", "rule", rule.id, vehicle_id, rule.service_type.name,
                                res.status, describe(res, today), res.progress,
                                res.effective_date, cycle, km_remaining=res.km_remaining))
    for di in db.scalars(select(m.DateItem).where(m.DateItem.vehicle_id == vehicle_id)):
        items.append(date_item_status(di, today))
    items.sort(key=lambda i: (ORDER[i.status], i.due or date.max))
    return items


def date_item_status(di: m.DateItem, today: date) -> StatusItem:
    n = (di.due_date - today).days
    status = OVERDUE if n < 0 else DUE_SOON if n <= di.soon_days else OK
    if di.informational and status == OVERDUE:
        status = DUE_SOON
    progress = None
    if di.recurs_yearly:
        progress = min(1.5, max(0.0, 1 - n / 365))
    return StatusItem(f"date:{di.id}", "date", di.id, di.vehicle_id, di.title, status,
                      describe_date_item(di.due_date, today), progress, di.due_date,
                      di.due_date.isoformat(), informational=di.informational)


def all_items(db: Session, today: date, user_id: int | None = None) -> list[StatusItem]:
    """Every user's items (for the evaluator), or only one user's when user_id is given."""
    out: list[StatusItem] = []
    vq = select(m.Vehicle).where(m.Vehicle.archived.is_(False))
    dq = select(m.DateItem).where(m.DateItem.vehicle_id.is_(None))
    if user_id is not None:
        vq = vq.where(m.Vehicle.user_id == user_id)
        dq = dq.where(m.DateItem.user_id == user_id)
    for v in db.scalars(vq):
        for item in vehicle_items(db, v.id, today):
            item.owner_id = v.user_id
            out.append(item)
    for di in db.scalars(dq):
        item = date_item_status(di, today)
        item.owner_id = di.user_id
        out.append(item)
    return out
