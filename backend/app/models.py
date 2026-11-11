from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Vehicle(Base):
    __tablename__ = "vehicle"
    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str] = mapped_column(String(60), unique=True)
    make: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(60))
    year: Mapped[int]
    vin: Mapped[str | None] = mapped_column(String(32))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class OdometerReading(Base):
    __tablename__ = "odometer_reading"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    km: Mapped[int]
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(10), default="ui")  # ui | telegram | service
    is_correction: Mapped[bool] = mapped_column(Boolean, default=False)
    # a correction invalidates the readings above it
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False)


class ServiceType(Base):
    __tablename__ = "service_type"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    default_interval_km: Mapped[int | None]
    default_interval_months: Mapped[int | None]
    default_soon_km: Mapped[int] = mapped_column(default=1000)
    default_soon_days: Mapped[int] = mapped_column(default=30)


class ServiceRecord(Base):
    __tablename__ = "service_record"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    odometer_km: Mapped[int | None]
    cost_cents: Mapped[int] = mapped_column(default=0)
    vendor: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list["ServiceRecordItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    attachments: Mapped[list["Attachment"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ServiceRecordItem(Base):
    __tablename__ = "service_record_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_record_id: Mapped[int] = mapped_column(ForeignKey("service_record.id", ondelete="CASCADE"), index=True)
    service_type_id: Mapped[int] = mapped_column(ForeignKey("service_type.id"))
    cost_cents: Mapped[int | None]


class Attachment(Base):
    __tablename__ = "attachment"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_record_id: Mapped[int] = mapped_column(ForeignKey("service_record.id", ondelete="CASCADE"), index=True)
    orig_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(80))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))


class ReminderRule(Base):
    __tablename__ = "reminder_rule"
    __table_args__ = (UniqueConstraint("vehicle_id", "service_type_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    service_type_id: Mapped[int] = mapped_column(ForeignKey("service_type.id"))
    interval_km: Mapped[int | None]
    interval_months: Mapped[int | None]
    soon_km: Mapped[int] = mapped_column(default=1000)
    soon_days: Mapped[int] = mapped_column(default=30)
    baseline_date: Mapped[date | None] = mapped_column(Date)
    baseline_km: Mapped[int | None]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    service_type: Mapped[ServiceType] = relationship(lazy="joined")


class DateItem(Base):
    __tablename__ = "date_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # registration|insurance|winter_install|winter_remove|custom
    title: Mapped[str] = mapped_column(String(120))
    due_date: Mapped[date] = mapped_column(Date)
    recurs_yearly: Mapped[bool] = mapped_column(Boolean, default=True)
    soon_days: Mapped[int] = mapped_column(default=30)
    informational: Mapped[bool] = mapped_column(Boolean, default=False)


class TireSet(Base):
    __tablename__ = "tire_set"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    season: Mapped[str] = mapped_column(String(10))  # winter | summer | all_season
    size: Mapped[str | None] = mapped_column(String(30))
    brand_model: Mapped[str | None] = mapped_column(String(80))
    dot_code: Mapped[str | None] = mapped_column(String(20))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    cost_cents: Mapped[int | None]
    storage_location: Mapped[str | None] = mapped_column(String(120))
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    mounts: Mapped[list["TireMount"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    treads: Mapped[list["TireTread"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class TireMount(Base):
    __tablename__ = "tire_mount"
    id: Mapped[int] = mapped_column(primary_key=True)
    tire_set_id: Mapped[int] = mapped_column(ForeignKey("tire_set.id", ondelete="CASCADE"), index=True)
    mounted_date: Mapped[date] = mapped_column(Date)
    mounted_km: Mapped[int]
    removed_date: Mapped[date | None] = mapped_column(Date)
    removed_km: Mapped[int | None]


class TireTread(Base):
    __tablename__ = "tire_tread"
    id: Mapped[int] = mapped_column(primary_key=True)
    tire_set_id: Mapped[int] = mapped_column(ForeignKey("tire_set.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    depth_mm: Mapped[float]


class AlertState(Base):
    __tablename__ = "alert_state"
    __table_args__ = (UniqueConstraint("subject", "cycle_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(40))  # rule:12 | date:5
    cycle_key: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realerted: Mapped[bool] = mapped_column(Boolean, default=False)


from app.notify.models import NotificationOutbox  # noqa: E402,F401  (re-export; table lives in the reusable notify package)
