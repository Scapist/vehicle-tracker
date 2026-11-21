from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.api.deps import owned_date_item, owned_rule, owned_tire_set, owned_vehicle, usable_type_ids
from app.auth import current_user
from app.clock import now_utc, today_local
from app.db import get_db
from app.domain.due import roll_yearly
from app.services import evaluator_hook, odometer, records, status, tires, views

router = APIRouter(tags=["rules"])


class Snooze(BaseModel):
    days: int = Field(default=7, ge=1, le=365)


@router.get("/vehicles/{vehicle_id}/rules", response_model=list[s.RuleOut])
def list_rules(vehicle_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_vehicle(db, user, vehicle_id)
    return list(db.scalars(select(m.ReminderRule).where(m.ReminderRule.vehicle_id == vehicle_id)))


@router.post("/vehicles/{vehicle_id}/rules", response_model=s.RuleOut, status_code=201)
def create_rule(vehicle_id: int, body: s.RuleIn, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    owned_vehicle(db, user, vehicle_id)
    if body.interval_km is None and body.interval_months is None:
        raise HTTPException(422, "Set a km interval, a months interval, or both")
    if body.service_type_id not in usable_type_ids(db, user):
        raise HTTPException(422, "Unknown service type")
    rule = m.ReminderRule(vehicle_id=vehicle_id, **body.model_dump())
    db.add(rule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This vehicle already has a rule for that service")
    evaluator_hook.after_change(db, user.id)
    return rule


@router.patch("/rules/{rule_id}", response_model=s.RuleOut)
def patch_rule(rule_id: int, body: s.RulePatch, user: m.User = Depends(current_user),
               db: Session = Depends(get_db)):
    rule = owned_rule(db, user, rule_id)
    nullable = {"interval_km", "interval_months", "baseline_date", "baseline_km"}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k not in nullable:
            continue
        setattr(rule, k, v)
    if rule.interval_km is None and rule.interval_months is None:
        db.rollback()
        raise HTTPException(422, "A rule needs a km interval, a months interval, or both")
    db.commit()
    evaluator_hook.after_change(db, user.id)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.evaluator import forget_alerts

    db.delete(owned_rule(db, user, rule_id))
    forget_alerts(db, f"rule:{rule_id}")
    db.commit()


@router.post("/rules/{rule_id}/done", response_model=s.ServiceOut, status_code=201)
def rule_done_today(rule_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rec = mark_rule_done(db, owned_rule(db, user, rule_id))
    return views.service_out(db, rec)


def mark_rule_done(db: Session, rule: m.ReminderRule):
    """Logs the service today at the current km (used by the UI button and the Telegram button).
    Callers must have checked ownership."""
    rec = records.log_service(db, rule.vehicle_id, today_local(), odometer.current_km(db, rule.vehicle_id), 0,
                              None, None, [(rule.service_type_id, None)])
    evaluator_hook.after_change(db, db.get(m.Vehicle, rule.vehicle_id).user_id)
    return rec


@router.post("/rules/{rule_id}/snooze", status_code=204)
def snooze_rule(rule_id: int, body: Snooze | None = None, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    owned_rule(db, user, rule_id)
    snooze_subject(db, user, f"rule:{rule_id}", (body or Snooze()).days)


@router.delete("/rules/{rule_id}/snooze", status_code=204)
def unsnooze_rule(rule_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_rule(db, user, rule_id)
    for st in db.scalars(select(m.AlertState).where(m.AlertState.subject == f"rule:{rule_id}")):
        st.snoozed_until = None
    db.commit()


def snooze_subject(db: Session, user: m.User, subject: str, days: int) -> None:
    today = today_local()
    item = next((i for i in status.all_items(db, today, user_id=user.id) if i.subject == subject), None)
    if not item:
        raise HTTPException(404)
    st = db.scalar(select(m.AlertState).where(m.AlertState.subject == subject,
                                              m.AlertState.cycle_key == item.cycle_key))
    if not st:
        st = m.AlertState(subject=subject, cycle_key=item.cycle_key, status=item.status)
        db.add(st)
    st.snoozed_until = now_utc() + timedelta(days=days)
    st.realerted = False
    db.commit()


# ---- date items ----

@router.get("/date-items", response_model=list[s.DateItemOut])
def list_date_items(vehicle_id: int | None = None, user: m.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    q = select(m.DateItem).where(m.DateItem.user_id == user.id).order_by(m.DateItem.due_date)
    if vehicle_id is not None:
        q = q.where(m.DateItem.vehicle_id == vehicle_id)
    return list(db.scalars(q))


@router.post("/date-items", response_model=s.DateItemOut, status_code=201)
def create_date_item(body: s.DateItemIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if body.vehicle_id is not None:
        owned_vehicle(db, user, body.vehicle_id)
    di = m.DateItem(**body.model_dump(), user_id=user.id)
    db.add(di)
    db.commit()
    evaluator_hook.after_change(db, user.id)
    return di


@router.delete("/date-items/{item_id}", status_code=204)
def delete_date_item(item_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.evaluator import forget_alerts

    db.delete(owned_date_item(db, user, item_id))
    forget_alerts(db, f"date:{item_id}")
    db.commit()


@router.post("/date-items/{item_id}/done", response_model=s.DateItemOut | None)
def date_item_done(item_id: int, body: s.DateItemDone | None = None, user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    di = owned_date_item(db, user, item_id)
    if body and body.tire_set_id is not None:
        ts = owned_tire_set(db, user, body.tire_set_id)
        if not tires.is_mounted(ts):
            try:
                tires.mount(db, ts, today_local())
            except tires.TireError as e:
                raise HTTPException(409, str(e))
    if di.recurs_yearly:
        di.due_date = roll_yearly(di.due_date, today_local())
        db.commit()
        evaluator_hook.after_change(db, user.id)
        return di
    db.delete(di)
    db.commit()
    return None
