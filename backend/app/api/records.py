import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.api.deps import (
    owned_attachment, owned_service, owned_service_type, owned_vehicle, usable_type_ids, visible_service_types,
)
from app.auth import current_user
from app.clock import today_local
from app.db import get_db
from app.services import evaluator_hook, records, views

router = APIRouter(tags=["services"])
MAX_FILES = 10
MAX_ATTACHMENTS = 30


def _type_out(t: m.ServiceType) -> s.ServiceTypeOut:
    out = s.ServiceTypeOut.model_validate(t)
    out.custom = t.user_id is not None
    return out


def _same_name(db: Session, user: m.User, name: str, exclude: int | None = None) -> m.ServiceType | None:
    q = select(m.ServiceType).where(visible_service_types(user), func.lower(m.ServiceType.name) == name.lower())
    if exclude is not None:
        q = q.where(m.ServiceType.id != exclude)
    return db.scalars(q).first()


@router.get("/service-types", response_model=list[s.ServiceTypeOut])
def service_types(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """The built-in types and this user's own, alphabetically."""
    q = select(m.ServiceType).where(visible_service_types(user)).order_by(func.lower(m.ServiceType.name))
    return [_type_out(t) for t in db.scalars(q)]


@router.post("/service-types", response_model=s.ServiceTypeOut, status_code=201)
def create_service_type(body: s.ServiceTypeIn, response: Response, user: m.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Add a service of your own. If one with that name already exists for you, you get that one back."""
    existing = _same_name(db, user, body.name)
    if existing:
        response.status_code = 200
        return _type_out(existing)
    t = m.ServiceType(key=f"custom-{uuid.uuid4().hex[:12]}", name=body.name, user_id=user.id,
                      default_interval_km=None, default_interval_months=None, default_soon_km=1000,
                      default_soon_days=30)
    db.add(t)
    db.commit()
    return _type_out(t)


@router.patch("/service-types/{type_id}", response_model=s.ServiceTypeOut)
def rename_service_type(type_id: int, body: s.ServiceTypeIn, user: m.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    t = owned_service_type(db, user, type_id)
    if _same_name(db, user, body.name, exclude=t.id):
        raise HTTPException(409, f"You already have a service called “{body.name}”")
    t.name = body.name
    db.commit()
    return _type_out(t)


@router.delete("/service-types/{type_id}", status_code=204)
def delete_service_type(type_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned_service_type(db, user, type_id)
    used = db.scalar(select(func.count()).select_from(m.ServiceRecordItem)
                     .where(m.ServiceRecordItem.service_type_id == t.id))
    rules = db.scalar(select(func.count()).select_from(m.ReminderRule).where(m.ReminderRule.service_type_id == t.id))
    if used or rules:
        raise HTTPException(409, "It's used in your service history or a reminder, so it can only be renamed")
    db.delete(t)
    db.commit()


@router.get("/services/{service_id}", response_model=s.ServiceOut)
def get_service(service_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return views.service_out(db, owned_service(db, user, service_id))


@router.get("/vehicles/{vehicle_id}/services", response_model=list[s.ServiceOut])
def list_services(vehicle_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_vehicle(db, user, vehicle_id)
    q = (select(m.ServiceRecord).where(m.ServiceRecord.vehicle_id == vehicle_id)
         .order_by(m.ServiceRecord.date.desc(), m.ServiceRecord.id.desc()))
    return [views.service_out(db, r) for r in db.scalars(q)]


@router.post("/services", response_model=s.ServiceOut, status_code=201)
async def create_service(
    vehicle_id: int = Form(),
    on: date = Form(alias="date"),
    odometer_km: int | None = Form(default=None, ge=0, le=2_000_000),
    cost_cents: int = Form(default=0, ge=0, le=100_000_000),
    vendor: str | None = Form(default=None, max_length=120),
    notes: str | None = Form(default=None, max_length=5000),
    type_ids: list[int] = Form(default=[]),
    item_costs: str | None = Form(default=None, description="JSON map of service_type_id -> cents"),
    files: list[UploadFile] = File(default=[]),
    user: m.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    owned_vehicle(db, user, vehicle_id)
    if on > today_local():
        raise HTTPException(422, "The service date can't be in the future")
    try:
        costs: dict[str, int] = {str(k): int(v) for k, v in (json.loads(item_costs) if item_costs else {}).items()}
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise HTTPException(422, "item_costs must be a JSON object of service type id -> cents")
    if any(v < 0 for v in costs.values()):
        raise HTTPException(422, "Item costs can't be negative")
    if sum(costs.values()) > cost_cents:
        raise HTTPException(422, "Item costs add up to more than the total")
    known = usable_type_ids(db, user)
    if any(t not in known for t in type_ids):
        raise HTTPException(422, "Unknown service type")
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"Attach at most {MAX_FILES} files at a time")
    uploads = []
    for f in files:
        data = await f.read(records.MAX_UPLOAD + 1)  # never read more than the cap into memory
        if records.sniff_mime(data) is None or len(data) > records.MAX_UPLOAD:
            raise HTTPException(422, f"{f.filename}: use a JPEG, PNG, WebP, HEIC or PDF under 20 MB")
        uploads.append((f.filename or "receipt", data))
    rec = records.log_service(db, vehicle_id, on, odometer_km, cost_cents, vendor, notes,
                              [(t, costs.get(str(t))) for t in dict.fromkeys(type_ids)], commit=False)
    for name, data in uploads:
        records.save_attachment(db, rec, name, data)
    db.commit()
    db.refresh(rec)
    evaluator_hook.after_change(db, user.id)
    return views.service_out(db, rec)


@router.delete("/services/{service_id}", status_code=204)
def delete_service(service_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rec = owned_service(db, user, service_id)
    paths = [records.attachment_path(att) for att in rec.attachments]
    db.delete(rec)
    db.commit()  # first, so a failed commit never leaves rows pointing at deleted files
    for path in paths:
        path.unlink(missing_ok=True)


@router.post("/services/{service_id}/attachments", response_model=s.AttachmentOut, status_code=201)
async def add_attachment(service_id: int, file: UploadFile = File(), user: m.User = Depends(current_user),
                         db: Session = Depends(get_db)):
    rec = owned_service(db, user, service_id)
    try:
        if len(rec.attachments) >= MAX_ATTACHMENTS:
            raise records.UploadError(f"A service can have at most {MAX_ATTACHMENTS} receipts")
        att = records.save_attachment(db, rec, file.filename or "receipt", await file.read(records.MAX_UPLOAD + 1))
    except records.UploadError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return att


@router.get("/attachments/{attachment_id}")
def get_attachment(attachment_id: int, download: bool = False, user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    att = owned_attachment(db, user, attachment_id)
    try:
        path = records.attachment_path(att)
    except FileNotFoundError:
        raise HTTPException(404, "File is missing from disk")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    if att.mime.startswith("image/"):
        # an image never needs to run anything
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return FileResponse(path, media_type=att.mime, filename=att.orig_name if download else None,
                        content_disposition_type="attachment" if download else "inline", headers=headers)
