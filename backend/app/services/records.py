"""Service records and receipt files."""
import hashlib
import uuid
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.clock import now_utc, today_local, tz
from app.config import settings
from app.services import odometer

MAX_UPLOAD = 20 * 1024 * 1024
HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic",
       "application/pdf": ".pdf"}


class UploadError(ValueError):
    pass


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS:
        return "image/heic"
    if data.startswith(b"%PDF"):
        return "application/pdf"
    return None


def receipts_dir() -> Path:
    return settings.data_dir / "receipts"


def attachment_path(att: m.Attachment) -> Path:
    for p in receipts_dir().glob(f"*/{att.stored_name}"):
        return p
    raise FileNotFoundError(att.stored_name)


def save_attachment(db: Session, record: m.ServiceRecord, filename: str, data: bytes) -> m.Attachment:
    if len(data) > MAX_UPLOAD:
        raise UploadError("File is larger than 20 MB")
    mime = sniff_mime(data)
    if not mime:
        raise UploadError("Unsupported file type. Use JPEG, PNG, WebP, HEIC or PDF")
    stored = uuid.uuid4().hex + EXT[mime]
    folder = receipts_dir() / str(record.date.year)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored).write_bytes(data)
    att = m.Attachment(service_record_id=record.id, orig_name=Path(filename or "receipt").name[:255],
                       stored_name=stored, mime=mime, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    db.add(att)
    db.flush()
    return att


def log_service(db: Session, vehicle_id: int, on: date, odometer_km: int | None, cost_cents: int,
                vendor: str | None, notes: str | None, items: list[tuple[int, int | None]],
                commit: bool = True) -> m.ServiceRecord:
    rec = m.ServiceRecord(vehicle_id=vehicle_id, date=on, odometer_km=odometer_km, cost_cents=cost_cents,
                          vendor=vendor or None, notes=notes or None)
    rec.items = [m.ServiceRecordItem(service_type_id=t, cost_cents=c) for t, c in items]
    db.add(rec)
    db.flush()
    cur = odometer.current_km(db, vehicle_id)
    if odometer_km is not None and (cur is None or odometer_km > cur):
        at = now_utc() if on == today_local() else datetime.combine(on, time(12), tzinfo=tz())
        odometer.add_reading(db, vehicle_id, odometer_km, source="service", recorded_at=at, commit=False)
    if commit:
        db.commit()
    return rec


def type_names(db: Session, rec: m.ServiceRecord) -> list[str]:
    ids = [i.service_type_id for i in rec.items]
    if not ids:
        return []
    names = dict(db.execute(select(m.ServiceType.id, m.ServiceType.name).where(m.ServiceType.id.in_(ids))).all())
    return [names[i] for i in ids if i in names]
