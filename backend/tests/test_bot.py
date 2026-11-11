from sqlalchemy import select

from app import models as m
from app.bot import logic
from app.services import odometer, records
from tests.conftest import TODAY

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 50


def add_truck(db, km=120000):
    owner = db.scalar(select(m.User))
    t = m.Vehicle(nickname="Truck", make="Ford", model="F150", year=2015, user_id=owner.id)
    db.add(t)
    db.flush()
    odometer.add_reading(db, t.id, km)
    return t


def test_bare_number_goes_to_closest_vehicle_below_with_wrong_vehicle_button(demo, user):
    add_truck(demo)
    r = logic.handle_text(demo, user, "84,700 km")
    assert "Logged 84,700 km for Civic (+200 km)" in r.text
    assert r.buttons[0][0] == "Wrong vehicle"
    assert odometer.current_km(demo, 1) == 84700


def test_nickname_overrides_guess(demo, user):
    t = add_truck(demo)
    r = logic.handle_text(demo, user, "truck 120500")
    assert "Truck" in r.text and odometer.current_km(demo, t.id) == 120500


def test_wrong_vehicle_removes_reading_and_offers_other(demo, user):
    t = add_truck(demo)
    r = logic.handle_text(demo, user, "85000")
    wrong = next(cb for _, cb in r.buttons if cb.startswith("wrong:"))
    r2 = logic.handle_callback(demo, user, wrong)
    assert odometer.current_km(demo, 1) == 84500  # reading removed
    assert r2.buttons == [("Truck", f"km:{t.id}:85000")]


def test_implausible_asks_which_vehicle(demo, user):
    add_truck(demo)
    r = logic.handle_text(demo, user, "10000")
    assert "Which vehicle" in r.text and len(r.buttons) == 2


def test_lower_value_asks_correction_then_applies(demo, user):
    r = logic.handle_text(demo, user, "80000")  # single... two vehicles not needed: only Civic exists
    assert "correction" in r.text.lower() and odometer.current_km(demo, 1) == 84500
    corr = next(cb for _, cb in r.buttons if cb.startswith("corr:"))
    logic.handle_callback(demo, user, corr)
    assert odometer.current_km(demo, 1) == 80000


def test_huge_jump_needs_confirmation(demo, user):
    r = logic.handle_text(demo, user, "95000")
    assert "Log it?" in r.text and odometer.current_km(demo, 1) == 84500
    logic.handle_callback(demo, user, r.buttons[0][1])
    assert odometer.current_km(demo, 1) == 95000


def test_parse_error_and_unknown_nickname_reply(demo, user):
    assert "ambiguous" in logic.handle_text(demo, user, "84.5").text
    assert "bike" in logic.handle_text(demo, user, "84500 bike").text


def test_done_today_and_undo(demo, user):
    rule = demo.scalar(select(m.ReminderRule).join(m.ServiceType).where(m.ServiceType.key == "oil"))
    r = logic.handle_callback(demo, user, f"done:rule:{rule.id}")
    assert "Oil change" in r.text and "84,500" in r.text
    rec = demo.scalar(select(m.ServiceRecord).order_by(m.ServiceRecord.id.desc()))
    assert rec.date == TODAY and rec.odometer_km == 84500
    logic.handle_callback(demo, user, r.buttons[0][1])
    assert demo.get(m.ServiceRecord, rec.id) is None


def test_snooze_button(demo, user):
    r = logic.handle_callback(demo, user, "snooze:rule:1:7")
    assert "Snoozed" in r.text
    assert demo.scalar(select(m.AlertState).where(m.AlertState.subject == "rule:1")).snoozed_until


def test_receipt_attaches_to_recent_visit(demo, user):
    records.log_service(demo, 1, TODAY, 84500, 1000, None, None, [(1, None)])
    r = logic.handle_attachment(demo, user, "r.jpg", JPEG)
    assert "Attached" in r.text
    assert len(demo.scalars(select(m.Attachment)).all()) == 1


def test_receipt_with_no_recent_visit_creates_receipt_only_entry(demo, user):
    r = logic.handle_attachment(demo, user, "r.jpg", JPEG)
    assert "receipt-only" in r.text
    rec = demo.scalar(select(m.ServiceRecord).order_by(m.ServiceRecord.id.desc()))
    assert rec.date == TODAY and len(rec.attachments) == 1 and rec.items == []


def test_receipt_rejects_bad_file(demo, user):
    assert "only file" in logic.handle_attachment(demo, user, "x", b"MZ....").text


def test_commands(demo, user):
    assert "Oil change" in logic.cmd_due(demo, user).text
    assert "84,500 km" in logic.cmd_vehicles(demo, user).text
    assert "/due" in logic.cmd_help(demo, user).text


def test_stale_button_does_not_crash(demo, user):
    assert "no longer" in logic.handle_callback(demo, user, "done:rule:999").text
    assert "didn't understand" in logic.handle_callback(demo, user, "garbage").text
