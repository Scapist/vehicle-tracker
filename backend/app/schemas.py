from datetime import date as Date
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VehicleIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=60)
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    year: int = Field(ge=1900, le=2100)
    vin: str | None = Field(default=None, max_length=32)


class VehiclePatch(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=60)
    make: str | None = Field(default=None, min_length=1, max_length=60)
    model: str | None = Field(default=None, min_length=1, max_length=60)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vin: str | None = Field(default=None, max_length=32)
    archived: bool | None = None
    nudge_days: int | None = Field(default=None, ge=0, le=365)


class VehicleOut(ORM):
    id: int
    nickname: str
    make: str
    model: str
    year: int
    vin: str | None
    archived: bool
    nudge_days: int = 14
    current_km: int | None = None
    worst_status: str = "ok"


class OdometerIn(BaseModel):
    km: int = Field(ge=0, le=5_000_000)
    is_correction: bool = False
    recorded_on: Date | None = None


class OdometerOut(ORM):
    id: int
    km: int
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        # SQLite hands back naive datetimes that are really UTC; make that explicit for clients
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
    source: str
    is_correction: bool
    invalidated: bool


class ServiceTypeOut(ORM):
    id: int
    key: str
    name: str
    default_interval_km: int | None
    default_interval_months: int | None
    default_soon_km: int
    default_soon_days: int
    custom: bool = False


class ServiceTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("must not be empty")
        return v


class AttachmentOut(ORM):
    id: int
    orig_name: str
    mime: str
    size: int


class ServiceItemOut(ORM):
    service_type_id: int
    cost_cents: int | None


class ServiceOut(ORM):
    id: int
    vehicle_id: int
    date: Date
    odometer_km: int | None
    cost_cents: int
    vendor: str | None
    notes: str | None
    items: list[ServiceItemOut]
    attachments: list[AttachmentOut]
    type_names: list[str] = []


class ServicePatch(BaseModel):
    """Fields to change on a logged service; leave a field out to keep it. type_ids replaces the list."""
    date: Date | None = None
    odometer_km: int | None = Field(default=None, ge=0, le=2_000_000)
    cost_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    vendor: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=5000)
    type_ids: list[int] | None = Field(default=None, max_length=50)


class StatusItemOut(BaseModel):
    subject: str
    kind: str
    id: int
    vehicle_id: int | None
    title: str
    status: str
    detail: str
    progress: float | None
    due: Date | None
    informational: bool = False


class RuleIn(BaseModel):
    service_type_id: int
    interval_km: int | None = Field(default=None, gt=0, le=1_000_000)
    interval_months: int | None = Field(default=None, gt=0, le=240)
    soon_km: int = Field(default=1000, ge=0, le=1_000_000)
    soon_days: int = Field(default=30, ge=0, le=3650)
    baseline_date: Date | None = None
    baseline_km: int | None = Field(default=None, ge=0, le=2_000_000)
    enabled: bool = True


class RulePatch(BaseModel):
    interval_km: int | None = Field(default=None, gt=0, le=1_000_000)
    interval_months: int | None = Field(default=None, gt=0, le=240)
    soon_km: int | None = Field(default=None, ge=0, le=1_000_000)
    soon_days: int | None = Field(default=None, ge=0, le=3650)
    baseline_date: Date | None = None
    baseline_km: int | None = Field(default=None, ge=0, le=2_000_000)
    enabled: bool | None = None


class RuleOut(ORM):
    id: int
    vehicle_id: int
    service_type_id: int
    interval_km: int | None
    interval_months: int | None
    soon_km: int
    soon_days: int
    baseline_date: Date | None
    baseline_km: int | None
    enabled: bool


class DateItemIn(BaseModel):
    vehicle_id: int | None = None
    kind: str = "custom"
    title: str = Field(min_length=1, max_length=120)
    due_date: Date
    recurs_yearly: bool = False
    soon_days: int = Field(default=30, ge=0, le=3650)
    informational: bool = False


class DateItemOut(ORM):
    id: int
    vehicle_id: int | None
    kind: str
    title: str
    due_date: Date
    recurs_yearly: bool
    soon_days: int
    informational: bool


class DateItemDone(BaseModel):
    tire_set_id: int | None = None


class TireTreadIn(BaseModel):
    date: Date | None = None
    depth_mm: float = Field(gt=0, le=20)


class TireTreadOut(ORM):
    id: int
    date: Date
    depth_mm: float


class TireMountOut(ORM):
    id: int
    mounted_date: Date
    mounted_km: int
    removed_date: Date | None
    removed_km: int | None


class TireSetIn(BaseModel):
    vehicle_id: int
    label: str
    season: str = Field(pattern="^(winter|summer|all_season)$")
    size: str | None = None
    brand_model: str | None = None
    dot_code: str | None = None
    purchase_date: Date | None = None
    cost_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    storage_location: str | None = None


class TireSetPatch(BaseModel):
    label: str | None = None
    size: str | None = None
    brand_model: str | None = None
    dot_code: str | None = None
    storage_location: str | None = None
    retired: bool | None = None


class TireSetOut(ORM):
    id: int
    vehicle_id: int
    label: str
    season: str
    size: str | None
    brand_model: str | None
    dot_code: str | None
    purchase_date: Date | None
    cost_cents: int | None
    storage_location: str | None
    retired: bool
    mounts: list[TireMountOut]
    treads: list[TireTreadOut]
    total_km: int = 0
    mounted: bool = False
    tread_warning: bool = False
    latest_tread_mm: float | None = None


class DashboardOut(BaseModel):
    vehicle: VehicleOut
    km_per_day: float | None
    items: list[StatusItemOut]
    recent_services: list[ServiceOut]
    year_cost_cents: int
    year: int
    mounted_tire_set: TireSetOut | None


class RecurringCostIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    amount_cents: int = Field(gt=0, le=100_000_000)
    every_months: int = 1
    start_date: Date
    end_date: Date | None = None
    remind_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("every_months")
    @classmethod
    def _every(cls, v: int) -> int:
        if v not in (1, 3, 6, 12):
            raise ValueError("must be 1, 3, 6 or 12")
        return v


class RecurringCostPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    amount_cents: int | None = Field(default=None, gt=0, le=100_000_000)
    every_months: int | None = None
    start_date: Date | None = None
    end_date: Date | None = None
    remind_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("every_months")
    @classmethod
    def _every(cls, v: int | None) -> int | None:
        if v is not None and v not in (1, 3, 6, 12):
            raise ValueError("must be 1, 3, 6 or 12")
        return v


class RecurringCostOut(ORM):
    id: int
    vehicle_id: int
    name: str
    category: str
    amount_cents: int
    every_months: int
    start_date: Date
    end_date: Date | None
    remind_days: int | None
    notes: str | None
    next_date: Date | None = None


class ChangeAmount(BaseModel):
    amount_cents: int = Field(gt=0, le=100_000_000)
    from_date: Date


class SpendingMonth(BaseModel):
    month: str
    total_cents: int
    by_category: dict[str, int]


class SpendingEntry(BaseModel):
    date: Date
    vehicle_id: int
    category: str
    cents: int
    source: str
    label: str
    ref_id: int
    scheduled: bool


class SpendingOut(BaseModel):
    total_cents: int
    scheduled_cents: int
    by_category: dict[str, int]
    by_month: list[SpendingMonth]
    entries: list[SpendingEntry]
    categories: list[str]
