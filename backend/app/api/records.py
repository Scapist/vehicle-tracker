import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.clock import today_local
from app.db import get_db
from app.services import evaluator_hook, records, views

router = APIRouter(tags=["services"])


@router.get("/service-types", response_model=list[s.ServiceTypeOut])
def service_types(db: Session = Depends(get_db)):
    return list(db.scalars(select(m.ServiceType).order_by(m.ServiceType.name)))


@router.get("/vehicles/{vehicle_id}/services", response_model=list[s.ServiceOut])
def list_services(vehicle_id: int, db: Session = Depends(get_db)):
    q = (select(m.ServiceRecord).where(m.ServiceRecord.vehicle_id == vehicle_id)
         .order_by(m.ServiceRecord.date.desc(), m.ServiceRecord.id.desc()))
    return [views.service_out(db, r) for r in db.scalars(q)]


@router.post("/services", response_model=s.ServiceOut, status_code=201)
async def create_service(
    vehicle_id: int = Form(),
    on: date = Form(alias="date"),
    odometer_km: int | None = Form(default=None, ge=0),
    cost_cents: int = Form(default=0, ge=0),
    vendor: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    type_ids: list[int] = Form(default=[]),
    item_costs: str | None = Form(default=None, description="JSON map of service_type_id -> cents"),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    if not db.get(m.Vehicle, vehicle_id):
        raise HTTPException(404, "Vehicle not found")
    if on > today_local():
        raise HTTPException(422, "The service date can't be in the future")
    try:
        costs: dict[str, int] = {str(k): int(v) for k, v in (json.loads(item_costs) if item_costs else {}).items()}
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "item_costs must be a JSON object of service type id -> cents")
    if any(v < 0 for v in costs.values()):
        raise HTTPException(422, "Item costs can't be negative")
    if sum(costs.values()) > cost_cents:
        raise HTTPException(422, "Item costs add up to more than the total")
    known = set(db.scalars(select(m.ServiceType.id)))
    if any(t not in known for t in type_ids):
        raise HTTPException(422, "Unknown service type")
    uploads = []
    for f in files:
        data = await f.read()
        if records.sniff_mime(data) is None or len(data) > records.MAX_UPLOAD:
            raise HTTPException(422, f"{f.filename}: use a JPEG, PNG, WebP, HEIC or PDF under 20 MB")
        uploads.append((f.filename or "receipt", data))
    rec = records.log_service(db, vehicle_id, on, odometer_km, cost_cents, vendor, notes,
                              [(t, costs.get(str(t))) for t in dict.fromkeys(type_ids)], commit=False)
    for name, data in uploads:
        records.save_attachment(db, rec, name, data)
    db.commit()
    db.refresh(rec)
    evaluator_hook.after_change(db)
    return views.service_out(db, rec)


@router.delete("/services/{service_id}", status_code=204)
def delete_service(service_id: int, db: Session = Depends(get_db)):
    rec = db.get(m.ServiceRecord, service_id)
    if not rec:
        raise HTTPException(404)
    for att in rec.attachments:
        try:
            records.attachment_path(att).unlink()
        except FileNotFoundError:
            pass
    db.delete(rec)
    db.commit()


@router.post("/services/{service_id}/attachments", response_model=s.AttachmentOut, status_code=201)
async def add_attachment(service_id: int, file: UploadFile = File(), db: Session = Depends(get_db)):
    rec = db.get(m.ServiceRecord, service_id)
    if not rec:
        raise HTTPException(404)
    try:
        att = records.save_attachment(db, rec, file.filename or "receipt", await file.read())
    except records.UploadError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return att


@router.get("/attachments/{attachment_id}")
def get_attachment(attachment_id: int, download: bool = False, db: Session = Depends(get_db)):
    att = db.get(m.Attachment, attachment_id)
    if not att:
        raise HTTPException(404)
    try:
        path = records.attachment_path(att)
    except FileNotFoundError:
        raise HTTPException(404, "File is missing from disk")
    return FileResponse(path, media_type=att.mime, filename=att.orig_name if download else None,
                        content_disposition_type="attachment" if download else "inline")
