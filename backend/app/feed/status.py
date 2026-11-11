"""Normalized status feed for the future shared dashboard."""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_user
from app.clock import today_local
from app.db import get_db
from app.services.status import all_items

router = APIRouter(tags=["feed"])


class FeedItem(BaseModel):
    source: str = "vehicle-tracker"
    subject: str
    title: str
    status: str
    due: date | None
    detail: str
    detail_url: str


@router.get("/status", response_model=list[FeedItem])
def status_feed(user=Depends(current_user), db: Session = Depends(get_db)):
    from app import models as m

    names = {v.id: v.nickname for v in db.query(m.Vehicle).filter(m.Vehicle.user_id == user.id).all()}
    out = []
    for i in all_items(db, today_local(), user_id=user.id):
        prefix = f"{names[i.vehicle_id]}: " if i.vehicle_id in names else ""
        out.append(FeedItem(subject=i.subject, title=prefix + i.title, status=i.status, due=i.due,
                            detail=i.detail,
                            detail_url=f"/vehicles/{i.vehicle_id}" if i.vehicle_id else "/"))
    return out
