import datetime as dt
import json

from sqlalchemy import select

from app import models as m
from app.bot.logic import handle_callback
from app.nudge import nudge_round, queue_nudges
from tests.conftest import TODAY, make_user

D = dt.date


def test_nudge_round():
    assert nudge_round(D(2026, 11, 1), D(2026, 11, 11), 14) is None  # 10 days: too soon
    assert nudge_round(D(2026, 10, 28), D(2026, 11, 11), 14) == 1  # exactly 14
    assert nudge_round(D(2026, 10, 1), D(2026, 11, 11), 14) == 2  # 41 days
    assert nudge_round(D(2026, 1, 1), D(2026, 11, 11), 0) is None  # off


def _vehicle(db, user, days_ago=15, km=84500, km_rule=True, **kw):
    v = m.Vehicle(nickname=kw.pop("nickname", "civic"), make="Honda", model="Civic", year=2020, user_id=user.id, **kw)
    db.add(v)
    db.flush()
    at = dt.datetime.combine(TODAY - dt.timedelta(days=days_ago), dt.time(12), tzinfo=dt.timezone.utc)
    db.add(m.OdometerReading(vehicle_id=v.id, km=km, recorded_at=at, source="ui"))
    oil = db.scalar(select(m.ServiceType).where(m.ServiceType.key == "oil"))
    db.add(m.ReminderRule(vehicle_id=v.id, service_type_id=oil.id, interval_km=8000 if km_rule else None,
                          interval_months=6, soon_km=1000, soon_days=30))
    db.commit()
    return v


def _outbox(db):
    return db.scalars(select(m.NotificationOutbox).order_by(m.NotificationOutbox.id)).all()


def test_asks_once_per_quiet_period(db, user):
    v = _vehicle(db, user)
    assert queue_nudges(db) == 1
    [msg] = _outbox(db)
    assert msg.title == "civic: what's the odometer at?"
    assert "84,500 km" in msg.body and "15 days ago" in msg.body and '"85,500"' in msg.body
    assert msg.recipient == f"user:{user.id}"
    assert json.loads(msg.actions_json) == [["Stop asking", f"nudge:off:{v.id}"]]
    assert queue_nudges(db) == 0  # same day, same period: nothing new
    assert queue_nudges(db, today=TODAY + dt.timedelta(days=5)) == 0
    assert queue_nudges(db, today=TODAY + dt.timedelta(days=14)) == 1  # still quiet 2 weeks later: ask again


def test_a_new_reading_resets_the_clock(db, user):
    v = _vehicle(db, user)
    assert queue_nudges(db) == 1
    db.add(m.OdometerReading(vehicle_id=v.id, km=85200, recorded_at=dt.datetime(2026, 11, 11, 17, tzinfo=dt.timezone.utc),
                             source="telegram"))
    db.commit()
    assert queue_nudges(db, today=TODAY + dt.timedelta(days=13)) == 0
    assert queue_nudges(db, today=TODAY + dt.timedelta(days=14)) == 1


def test_names_the_vehicle_when_there_are_several(db, user):
    _vehicle(db, user)
    _vehicle(db, user, nickname="truck", days_ago=3)
    assert queue_nudges(db) == 1
    assert '"civic 85,500"' in _outbox(db)[0].body


def test_who_is_not_asked(db, user):
    _vehicle(db, user, days_ago=10)  # too soon
    _vehicle(db, user, nickname="off", nudge_days=0)
    _vehicle(db, user, nickname="sold", archived=True)
    _vehicle(db, user, nickname="dates", km_rule=False)  # only time-based reminders: km doesn't matter
    unlinked = make_user(db, email="b@example.com", owner=False, chat_id=None)
    _vehicle(db, unlinked, nickname="theirs")
    assert queue_nudges(db) == 0


def test_stop_asking_button(db, user):
    v = _vehicle(db, user)
    other = make_user(db, email="b@example.com", owner=False, chat_id=222)
    assert "Couldn't find" in handle_callback(db, other, f"nudge:off:{v.id}").text
    assert db.get(m.Vehicle, v.id).nudge_days == 14
    assert "won't ask" in handle_callback(db, user, f"nudge:off:{v.id}").text
    assert db.get(m.Vehicle, v.id).nudge_days == 0
    assert queue_nudges(db) == 0


def test_setting_is_editable(client):
    vid = client.post("/api/v1/vehicles", json={"nickname": "civic", "make": "H", "model": "C", "year": 2020}).json()["id"]
    assert client.get(f"/api/v1/vehicles/{vid}").json()["nudge_days"] == 14
    assert client.patch(f"/api/v1/vehicles/{vid}", json={"nudge_days": 30}).json()["nudge_days"] == 30
    assert client.patch(f"/api/v1/vehicles/{vid}", json={"nudge_days": -1}).status_code == 422
