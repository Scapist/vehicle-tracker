import datetime as dt

from sqlalchemy import select

from app import models as m
from app.api.rules import mark_rule_done, snooze_subject
from app.clock import now_utc
from app.evaluator import evaluate
from app.notify.base import Action, LogNotifier
from app.notify.outbox import MAX_ATTEMPTS, dispatch, enqueue
from app.services import odometer
from tests.conftest import TODAY


def outbox(db):
    return db.scalars(select(m.NotificationOutbox).order_by(m.NotificationOutbox.id)).all()


def titles(db):
    return [o.title for o in outbox(db)]


def test_first_evaluation_alerts_once_and_second_adds_none(demo):
    n = evaluate(demo)
    assert n > 0
    first = titles(demo)
    assert any("Civic: Oil change is overdue" in t for t in first)
    assert not any("Winter tires can come off" in t for t in first)  # informational never alerts
    assert evaluate(demo) == 0
    assert titles(demo) == first


def count(db, text):
    return sum(text in t for t in titles(db))


def test_crossing_a_threshold_alerts_exactly_once(demo):
    evaluate(demo)
    assert count(demo, "Tire rotation") == 0
    # tire rotation: last 82,000 + 10,000 = 92,000; soon window 1,000
    odometer.add_reading(demo, 1, 91_200)
    evaluate(demo)
    assert count(demo, "Tire rotation is due soon") == 1
    evaluate(demo)
    assert count(demo, "Tire rotation") == 1
    odometer.add_reading(demo, 1, 92_100)  # soon -> overdue is a new transition
    evaluate(demo)
    assert count(demo, "Tire rotation is overdue") == 1 and count(demo, "Tire rotation") == 2
    evaluate(demo)
    assert count(demo, "Tire rotation") == 2


def test_new_cycle_after_service(demo):
    evaluate(demo)
    rule = demo.scalar(select(m.ReminderRule).join(m.ServiceType).where(m.ServiceType.key == "oil"))
    assert count(demo, "Oil change is overdue") == 1
    mark_rule_done(demo, rule)  # service at 84,500 -> new cycle, status ok
    evaluate(demo)
    assert count(demo, "Oil change") == 1
    odometer.add_reading(demo, 1, 92_000)  # 84,500 + 8,000 = 92,500 -> soon (window 1,000)
    evaluate(demo)
    assert count(demo, "Oil change is due soon") == 1
    evaluate(demo)
    assert count(demo, "Oil change") == 2


def test_snooze_suppresses_then_realerts_once(demo, user):
    evaluate(demo)
    count = len(outbox(demo))
    snooze_subject(demo, user, "rule:1", 7)
    assert evaluate(demo) == 0
    later = now_utc() + dt.timedelta(days=8)
    assert evaluate(demo, now=later) == 1
    assert "still" in titles(demo)[-1]
    assert evaluate(demo, now=later) == 0
    assert evaluate(demo, now=later + dt.timedelta(days=30)) == 0
    assert len(outbox(demo)) == count + 1


def test_snoozed_item_crossing_to_overdue_waits(demo, user):
    odometer.add_reading(demo, 1, 91_200)
    evaluate(demo)  # tire rotation due soon, alerted
    rot = demo.scalar(select(m.ReminderRule).join(m.ServiceType).where(m.ServiceType.key == "tire_rotation"))
    snooze_subject(demo, user, f"rule:{rot.id}", 7)
    odometer.add_reading(demo, 1, 92_500)
    before = len(outbox(demo))
    evaluate(demo)
    assert not any("Tire rotation is overdue" in t for t in titles(demo)[before:])


def test_outbox_dedupe_and_retry(db):
    assert enqueue(db, "t", "k1", "T", "B", [Action("Go", "go:1")])
    assert not enqueue(db, "t", "k1", "T", "B")
    db.commit()

    class Flaky:
        calls = 0

        def send(self, title, body, actions=None, recipient=None):
            Flaky.calls += 1
            if Flaky.calls < 3:
                raise RuntimeError("network down")

    f = Flaky()
    assert dispatch(db, f) == 0 and outbox(db)[0].attempts == 1 and "network down" in outbox(db)[0].last_error
    assert dispatch(db, f) == 0
    assert dispatch(db, f) == 1 and outbox(db)[0].sent_at is not None
    assert dispatch(db, f) == 0  # already sent, not resent


def test_outbox_gives_up_after_max_attempts(db):
    enqueue(db, "t", "k", "T", "B")
    db.commit()

    class Down:
        def send(self, *a, **k):
            raise RuntimeError("x")

    for _ in range(MAX_ATTEMPTS + 2):
        dispatch(db, Down())
    assert outbox(db)[0].attempts == MAX_ATTEMPTS


def test_dispatch_passes_actions_to_notifier(demo):
    evaluate(demo)
    n = LogNotifier()
    assert dispatch(demo, n) == len(n.sent) > 0
    assert any(a.callback_id.startswith("done:rule:") for _, _, acts in n.sent for a in acts)


def test_date_item_alert_and_roll_forward_new_cycle(demo):
    ins = demo.scalar(select(m.DateItem).where(m.DateItem.kind == "insurance"))
    ins.due_date = TODAY + dt.timedelta(days=10)
    demo.commit()
    evaluate(demo)
    assert any("Insurance renewal is due soon" in t for t in titles(demo))
    ins.due_date = dt.date(TODAY.year + 1, 1, 1) + dt.timedelta(days=0)
    demo.commit()
    assert evaluate(demo) == 0
