"""Seed service types always; demo data only via `python -m app.seed --demo`."""
import sys
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.db import SessionLocal

SERVICE_TYPES = [
    ("oil", "Oil change", 8000, 6, 1000, 30),
    ("tire_rotation", "Tire rotation", 10000, 6, 1000, 30),
    ("brake_inspection", "Brake inspection", 20000, 12, 1500, 30),
    ("engine_air_filter", "Engine air filter", 30000, 24, 2000, 45),
    ("cabin_filter", "Cabin filter", 20000, 12, 1500, 30),
    ("battery", "Battery", None, 48, 0, 60),
]


def seed_service_types(db: Session) -> None:
    have = set(db.scalars(select(m.ServiceType.key)))
    for key, name, km, mo, skm, sd in SERVICE_TYPES:
        if key not in have:
            db.add(m.ServiceType(key=key, name=name, default_interval_km=km, default_interval_months=mo,
                                 default_soon_km=skm, default_soon_days=sd))
    db.commit()


def seed_demo(db: Session, today: date | None = None) -> None:
    if db.scalar(select(m.Vehicle.id)):
        return
    today = today or date.today()
    v = m.Vehicle(nickname="Civic", make="Honda", model="Civic", year=2019)
    db.add(v)
    db.flush()
    # ~40 km/day over the last year
    for days_ago, km in [(365, 70000), (270, 73600), (180, 77200), (90, 80800), (30, 83300), (0, 84500)]:
        d = today - timedelta(days=days_ago)
        db.add(m.OdometerReading(vehicle_id=v.id, km=km, source="ui",
                                 recorded_at=datetime.combine(d, time(12), tzinfo=timezone.utc)))
    types = {t.key: t for t in db.scalars(select(m.ServiceType))}

    def visit(days_ago, km, cost, vendor, keys):
        r = m.ServiceRecord(vehicle_id=v.id, date=today - timedelta(days=days_ago), odometer_km=km,
                            cost_cents=cost, vendor=vendor)
        r.items = [m.ServiceRecordItem(service_type_id=types[k].id) for k in keys]
        db.add(r)

    visit(240, 76000, 8900, "Jiffy Lube", ["oil", "tire_rotation"])
    visit(400, 68000, 12000, "Honda Dealer", ["oil", "cabin_filter"])
    visit(60, 82000, 4500, "Garage Pro", ["tire_rotation"])
    for key in ["oil", "tire_rotation", "brake_inspection", "engine_air_filter", "cabin_filter"]:
        t = types[key]
        rule = m.ReminderRule(vehicle_id=v.id, service_type_id=t.id, interval_km=t.default_interval_km,
                              interval_months=t.default_interval_months, soon_km=t.default_soon_km,
                              soon_days=t.default_soon_days)
        if key in ("brake_inspection", "engine_air_filter"):
            rule.baseline_date = today - timedelta(days=500)
            rule.baseline_km = 62000
        db.add(rule)

    def next_annual(month: int, day: int) -> date:
        d = date(today.year, month, day)
        return d if d >= today else date(today.year + 1, month, day)

    db.add(m.DateItem(vehicle_id=v.id, kind="registration", title="Registration renewal",
                      due_date=next_annual(6, 30)))
    db.add(m.DateItem(vehicle_id=v.id, kind="insurance", title="Insurance renewal",
                      due_date=today + timedelta(days=75)))
    db.add(m.DateItem(vehicle_id=v.id, kind="winter_install", title="Install winter tires by Dec 1",
                      due_date=next_annual(12, 1)))
    db.add(m.DateItem(vehicle_id=v.id, kind="winter_remove", title="Winter tires can come off after Mar 15",
                      due_date=next_annual(3, 15), informational=True, soon_days=14))
    summer = m.TireSet(vehicle_id=v.id, label="Summer set", season="summer", size="215/55R16",
                       brand_model="Michelin Pilot", purchase_date=today - timedelta(days=900), cost_cents=62000)
    summer.mounts = [m.TireMount(mounted_date=today - timedelta(days=200), mounted_km=77000)]
    summer.treads = [m.TireTread(date=today - timedelta(days=30), depth_mm=5.5)]
    winter = m.TireSet(vehicle_id=v.id, label="Winter set", season="winter", size="205/60R16",
                       brand_model="Blizzak WS90", purchase_date=today - timedelta(days=1100), cost_cents=58000,
                       storage_location="Garage shelf")
    winter.mounts = [m.TireMount(mounted_date=today - timedelta(days=500), mounted_km=64000,
                                 removed_date=today - timedelta(days=200), removed_km=77000)]
    winter.treads = [m.TireTread(date=today - timedelta(days=210), depth_mm=4.5)]
    db.add_all([summer, winter])
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        seed_service_types(db)
        if "--demo" in sys.argv:
            seed_demo(db)


if __name__ == "__main__":
    main()
