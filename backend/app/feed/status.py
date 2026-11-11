"""Normalized status feed for the future shared dashboard."""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
def status_feed(db: Session = Depends(get_db)):
    from app import models as m

    names = {v.id: v.nickname for v in db.query(m.Vehicle).all()}
    out = []
    for i in all_items(db, today_local()):
        prefix = f"{names[i.vehicle_id]}: " if i.vehicle_id in names else ""
        out.append(FeedItem(subject=i.subject, title=prefix + i.title, status=i.status, due=i.due,
                            detail=i.detail,
                            detail_url=f"/vehicles/{i.vehicle_id}" if i.vehicle_id else "/"))
    return out
