"""Recurring payments (insurance, financing, registration…), counted as spent on their own."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.api.deps import owned_recurring_cost, owned_vehicle
from app.auth import current_user
from app.clock import today_local
from app.db import get_db
from app.domain.recurring import next_occurrence
from app.services import evaluator_hook

router = APIRouter(tags=["costs"])


def _out(rc: m.RecurringCost) -> s.RecurringCostOut:
    out = s.RecurringCostOut.model_validate(rc)
    out.next_date = next_occurrence(rc.start_date, rc.every_months, rc.end_date, today_local())
    return out


def _check(rc: m.RecurringCost) -> None:
    if rc.end_date and rc.end_date < rc.start_date:
        raise HTTPException(422, "The end date is before the first payment")
    if rc.every_months != 12:
        rc.remind_days = None  # only yearly payments get a heads-up


@router.get("/vehicles/{vehicle_id}/recurring-costs", response_model=list[s.RecurringCostOut])
def list_costs(vehicle_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_vehicle(db, user, vehicle_id)
    q = (select(m.RecurringCost).where(m.RecurringCost.vehicle_id == vehicle_id)
         .order_by(m.RecurringCost.name, m.RecurringCost.start_date))
    return [_out(rc) for rc in db.scalars(q)]


@router.post("/vehicles/{vehicle_id}/recurring-costs", response_model=s.RecurringCostOut, status_code=201)
def create_cost(vehicle_id: int, body: s.RecurringCostIn, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    owned_vehicle(db, user, vehicle_id)
    rc = m.RecurringCost(vehicle_id=vehicle_id, **body.model_dump())
    _check(rc)
    db.add(rc)
    db.commit()
    evaluator_hook.after_change(db, user.id)
    return _out(rc)


@router.patch("/recurring-costs/{cost_id}", response_model=s.RecurringCostOut)
def patch_cost(cost_id: int, body: s.RecurringCostPatch, user: m.User = Depends(current_user),
               db: Session = Depends(get_db)):
    rc = owned_recurring_cost(db, user, cost_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k in ("name", "category", "amount_cents", "every_months", "start_date"):
            continue  # required fields can't be cleared
        setattr(rc, k, v)
    _check(rc)
    db.commit()
    evaluator_hook.after_change(db, user.id)
    return _out(rc)


@router.delete("/recurring-costs/{cost_id}", status_code=204)
def delete_cost(cost_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_recurring_cost(db, user, cost_id))
    db.commit()


@router.post("/recurring-costs/{cost_id}/change-amount", response_model=s.RecurringCostOut, status_code=201)
def change_amount(cost_id: int, body: s.ChangeAmount, user: m.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """New price from a date on: this payment ends the day before, a copy carries on with the new amount,
    so earlier payments keep their old price."""
    rc = owned_recurring_cost(db, user, cost_id)
    if body.from_date <= rc.start_date:
        raise HTTPException(422, "Pick a date after the first payment, or edit the amount instead")
    if rc.end_date and body.from_date > rc.end_date:
        raise HTTPException(422, "This payment has already ended by then")
    new = m.RecurringCost(vehicle_id=rc.vehicle_id, name=rc.name, category=rc.category,
                          amount_cents=body.amount_cents, every_months=rc.every_months,
                          start_date=body.from_date, end_date=rc.end_date, remind_days=rc.remind_days,
                          notes=rc.notes)
    rc.end_date = body.from_date - timedelta(days=1)
    db.add(new)
    db.commit()
    evaluator_hook.after_change(db, user.id)
    return _out(new)
