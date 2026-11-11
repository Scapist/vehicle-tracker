"""Regression tests for the issues found in the one-pass code review."""
import datetime as dt

import httpx
import time_machine
from sqlalchemy import select

from app import models as m
from app.bot import logic
from app.domain.due import Anchor, Rule, compute_due, roll_yearly
from app.evaluator import evaluate
from app.notify.base import TelegramNotifier
from app.notify.outbox import MAX_ATTEMPTS, dispatch, enqueue, redact
from app.services import evaluator_hook
from tests.conftest import NOW, TODAY


def test_zero_interval_cannot_be_saved_and_does_not_crash(demo_client, demo):
    rid = demo_client.get("/api/v1/vehicles/1/rules").json()[0]["id"]
    assert demo_client.patch(f"/api/v1/rules/{rid}", json={"interval_km": 0}).status_code == 422
    # even if a bad row got in some other way, status is computed and nothing divides by zero
    r = compute_due(Rule(interval_km=0, interval_months=6), Anchor(TODAY, 1000), 2000, [], TODAY)
    assert r.status == "ok" and r.due_km is None
    rule = demo.get(m.ReminderRule, rid)
    rule.interval_km = 0
    demo.commit()
    assert demo_client.get("/api/v1/vehicles/1/dashboard").status_code == 200


def test_evaluator_failure_never_breaks_a_write(demo_client, monkeypatch):
    def boom(db):
        raise RuntimeError("evaluator exploded")

    monkeypatch.setattr("app.evaluator.evaluate", boom)
    evaluator_hook.after_change(_FakeDb())  # must not raise
    r = demo_client.post("/api/v1/vehicles/1/odometer", json={"km": 84600})
    assert r.status_code == 201


class _FakeDb:
    def rollback(self):
        pass


def test_one_broken_rule_does_not_stop_the_others(demo, monkeypatch):
    import app.services.status as st

    real = st.compute_due

    def flaky(rule, *a, **k):
        if rule.interval_km == 8000:  # the oil rule
            raise ValueError("bad rule")
        return real(rule, *a, **k)

    monkeypatch.setattr(st, "compute_due", flaky)
    assert evaluate(demo) > 0  # other overdue items still alert
    titles = [o.title for o in demo.scalars(select(m.NotificationOutbox))]
    assert not any("Oil change" in t for t in titles) and any("Brake" in t for t in titles)


def test_token_is_redacted_from_stored_errors(db):
    token = "123456789:AAH-secret_TOKEN"
    enqueue(db, "t", "k", "T", "B")
    db.commit()

    def handler(request):
        return httpx.Response(401, json={"ok": False})

    notifier = TelegramNotifier(token, [1], client=httpx.Client(transport=httpx.MockTransport(handler)))
    dispatch(db, notifier)
    row = db.scalar(select(m.NotificationOutbox))
    assert "401" in row.last_error and token not in row.last_error and "AAH" not in row.last_error
    assert redact(f"https://api.telegram.org/bot{token}/sendMessage") == "https://api.telegram.org/bot<redacted>/sendMessage"


def test_outbox_keeps_retrying_with_backoff_after_quick_attempts(db):
    enqueue(db, "t", "k", "T", "B")
    db.commit()
    calls = []

    class Down:
        def send(self, *a, **k):
            calls.append(1)
            raise RuntimeError("down")

    for _ in range(MAX_ATTEMPTS + 3):
        dispatch(db, Down())
    assert len(calls) == MAX_ATTEMPTS  # quick retries used up, now waiting
    with time_machine.travel(NOW + dt.timedelta(minutes=11), tick=False):
        dispatch(db, Down())
    assert len(calls) == MAX_ATTEMPTS + 1
    ok = type("Ok", (), {"send": lambda self, *a, **k: None})()
    with time_machine.travel(NOW + dt.timedelta(minutes=31), tick=False):
        assert dispatch(db, ok) == 1  # an outage of 30+ minutes still delivers eventually


def test_csv_empty_cells_stay_empty_but_formulas_are_neutralised(demo_client, demo):
    rec = demo.scalar(select(m.ServiceRecord))
    rec.vendor = "=HYPERLINK(1)"
    demo.commit()
    text = demo_client.get("/api/v1/export/services.csv").text
    assert "'=HYPERLINK(1)" in text
    tires = demo_client.get("/api/v1/export/tires.csv").text
    assert "'," not in tires and not tires.rstrip().endswith("'")


def test_future_dates_rejected(demo_client):
    tomorrow = (TODAY + dt.timedelta(days=1)).isoformat()
    assert demo_client.post("/api/v1/vehicles/1/odometer", json={"km": 90000, "recorded_on": tomorrow}).status_code == 422
    r = demo_client.post("/api/v1/services", data={"vehicle_id": 1, "date": tomorrow})
    assert r.status_code == 422


def test_bad_item_costs_are_422_not_500(demo_client):
    base = {"vehicle_id": 1, "date": TODAY.isoformat(), "cost_cents": 100, "type_ids": [1]}
    assert demo_client.post("/api/v1/services", data={**base, "item_costs": "{not json"}).status_code == 422
    assert demo_client.post("/api/v1/services", data={**base, "item_costs": '{"1": "abc"}'}).status_code == 422
    assert demo_client.post("/api/v1/services", data={**base, "item_costs": '{"1": -50}'}).status_code == 422
    assert demo_client.post("/api/v1/services", data={**base, "item_costs": "[1]"}).status_code == 422


def test_patch_with_explicit_nulls_does_not_500(demo_client):
    assert demo_client.patch("/api/v1/vehicles/1", json={"nickname": None}).status_code == 200
    assert demo_client.get("/api/v1/vehicles/1").json()["nickname"] == "Civic"
    rid = demo_client.get("/api/v1/vehicles/1/rules").json()[0]["id"]
    assert demo_client.patch(f"/api/v1/rules/{rid}", json={"soon_km": None}).status_code == 200
    sid = demo_client.get("/api/v1/tire-sets").json()[0]["id"]
    assert demo_client.patch(f"/api/v1/tire-sets/{sid}", json={"label": None}).status_code == 200


def test_yearly_roll_forward_never_lands_in_the_past():
    assert roll_yearly(dt.date(2026, 6, 30), TODAY) == dt.date(2027, 6, 30)
    assert roll_yearly(dt.date(2023, 3, 1), TODAY) == dt.date(2027, 3, 1)  # 3+ years overdue
    assert roll_yearly(dt.date(2026, 11, 20), TODAY) == dt.date(2027, 11, 20)


def test_done_today_is_idempotent_and_stale_undo_is_harmless(demo):
    rule = demo.scalar(select(m.ReminderRule).join(m.ServiceType).where(m.ServiceType.key == "oil"))
    first = logic.handle_callback(demo, f"done:rule:{rule.id}")
    second = logic.handle_callback(demo, f"done:rule:{rule.id}")  # double tap
    assert "Logged" in first.text and "already logged" in second.text
    todays = [r for r in demo.scalars(select(m.ServiceRecord)) if r.date == TODAY]
    assert len(todays) == 1
    # an old, detailed visit must not be deletable via a stale Undo button
    old = demo.scalar(select(m.ServiceRecord).where(m.ServiceRecord.vendor == "Jiffy Lube"))
    logic.handle_callback(demo, f"undo:{old.id}")
    assert demo.get(m.ServiceRecord, old.id) is not None


def test_odometer_timestamps_are_timezone_aware_in_the_api(demo_client):
    stamp = demo_client.get("/api/v1/vehicles/1/odometer").json()[0]["recorded_at"]
    assert stamp.endswith("Z") or "+00:00" in stamp
