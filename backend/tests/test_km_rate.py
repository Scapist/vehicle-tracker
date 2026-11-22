import datetime as dt

from sqlalchemy import select

from app import models as m
from app.domain.due import km_per_day
from app.services import odometer, records, status
from tests.conftest import TODAY


def _car(db, user, km_now=168_649):
    v = m.Vehicle(user_id=user.id, nickname="Legacy", make="Subaru", model="Legacy", year=2016)
    db.add(v)
    db.commit()
    odometer.add_reading(db, v.id, km_now)  # the only odometer reading: today
    return v


def _type(db, name):
    return db.scalar(select(m.ServiceType).where(m.ServiceType.name == name)).id


def test_logged_services_count_as_driving_history(db, user):
    v = _car(db, user)
    assert km_per_day(odometer.domain_readings(db, v.id), TODAY) is None  # one reading: no rate
    plugs = _type(db, "Spark plugs")
    # entered after the car was added, all below the current km
    records.log_service(db, v.id, TODAY - dt.timedelta(days=88), 164_700, 0, None, None, [])
    records.log_service(db, v.id, TODAY - dt.timedelta(days=420), 149_500, 0, None, None, [(plugs, None)])
    rate = km_per_day(odometer.domain_readings(db, v.id), TODAY)
    assert round(rate, 1) == round((168_649 - 164_700) / 88, 1)  # the last 90 days

    db.add(m.ReminderRule(vehicle_id=v.id, service_type_id=plugs, interval_km=100_000))
    db.commit()
    item = next(i for i in status.all_items(db, TODAY, user_id=user.id) if i.title == "Spark plugs")
    assert item.km_remaining == 249_500 - 168_649
    assert item.due is not None  # a date estimate, from km alone


def test_service_km_above_the_odometer_is_ignored(db, user):
    v = _car(db, user, km_now=50_000)
    records.log_service(db, v.id, TODAY - dt.timedelta(days=30), 40_000, 0, None, None, [])
    # a typo'd service (500,000 km) must not make the car look like it drives 15,000 km a day
    db.add(m.ServiceRecord(vehicle_id=v.id, date=TODAY - dt.timedelta(days=20), odometer_km=500_000, cost_cents=0))
    db.commit()
    assert round(km_per_day(odometer.domain_readings(db, v.id), TODAY)) == round(10_000 / 30)
