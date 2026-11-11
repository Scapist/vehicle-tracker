"""Regression tests for the second code review (accounts / security changes)."""
import datetime as dt

import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app import models as m
from app.config import settings
from app.db import get_db
from app.evaluator import evaluate, resolve_recipient
from app.main import app
from app.notify.base import LogNotifier
from app.notify.outbox import HOLD_LIMIT, dispatch
from app.security import MAX_BODY
from app.services import evaluator_hook
from tests.conftest import CHAT_ID, NOW, PASSWORD, TODAY, make_user, signed_in


def outbox(db):
    return db.scalars(select(m.NotificationOutbox).order_by(m.NotificationOutbox.id)).all()


class Recorder(LogNotifier):
    """A notifier that, like Telegram, refuses to send without an address."""

    def send(self, title, body, actions=None, recipient=None):
        if recipient is None:
            raise ValueError("no address")
        super().send(title, body, actions, recipient)


def tg_dispatch(db, notifier):
    return dispatch(db, notifier, resolve=lambda r: resolve_recipient(db, r))


# 1: alerts for someone without a linked chat wait instead of vanishing
def test_alert_waits_for_telegram_link_then_delivers(demo, user):
    user.telegram_chat_id = None
    demo.commit()
    evaluate(demo)
    n = Recorder()
    assert tg_dispatch(demo, n) == 0 and n.sent == []
    assert all(r.sent_at is None and r.attempts == 0 for r in outbox(demo))  # held, not burned
    user.telegram_chat_id = 777
    demo.commit()
    assert tg_dispatch(demo, n) == len(outbox(demo)) > 0
    assert set(n.recipients) == {"777"}


def test_held_alert_is_dropped_after_hold_limit(demo, user):
    user.telegram_chat_id = None
    demo.commit()
    evaluate(demo)
    with time_machine.travel(NOW + HOLD_LIMIT + dt.timedelta(hours=1), tick=False):
        tg_dispatch(demo, Recorder())
    assert all("never became reachable" in (r.last_error or "") for r in outbox(demo))
    user.telegram_chat_id = 777
    demo.commit()
    assert tg_dispatch(demo, Recorder()) == 0  # a week-old backlog doesn't flood the new chat


def test_pre_accounts_data_alerts_after_the_owner_claims_it(anon_db_with_orphan):
    db, client = anon_db_with_orphan
    assert evaluate(db) == 0  # nobody owns it yet: don't record a transition nobody will hear about
    code = auth.ensure_setup_code()
    r = client.post("/api/v1/auth/setup", json={"name": "Me", "email": "me@example.com", "password": PASSWORD,
                                                "setup_code": code})
    assert r.status_code == 201
    evaluate(db)
    assert any("Oil" in row.title for row in outbox(db))


# 4: the chat is looked up at send time
def test_queued_alert_follows_relink_and_respects_disconnect(demo, user):
    evaluate(demo)
    user.telegram_chat_id = 333  # moved to another chat after the alert was queued
    demo.commit()
    n = Recorder()
    tg_dispatch(demo, n)
    assert set(n.recipients) == {"333"} and str(CHAT_ID) not in n.recipients


def test_disconnected_user_gets_nothing(demo, user):
    evaluate(demo)
    user.telegram_chat_id = None
    demo.commit()
    n = Recorder()
    assert tg_dispatch(demo, n) == 0 and n.sent == []


# 9: a write re-evaluates only the writer's alerts
def test_one_users_write_does_not_evaluate_another_users_items(demo, user):
    sam = make_user(demo, "sam@example.com", "Sam", owner=False, chat_id=222)
    demo.add(m.DateItem(user_id=sam.id, kind="custom", title="Sam's inspection", due_date=TODAY))
    demo.commit()
    evaluator_hook.after_change(demo, user.id)
    assert not any("Sam's" in r.title for r in outbox(demo))
    assert any(r.title.startswith("Civic") for r in outbox(demo))
    evaluate(demo)  # the daily run covers everyone
    assert any("Sam's" in r.title for r in outbox(demo))


# 3: chunked uploads can't get around the size cap
def test_chunked_body_over_the_cap_is_rejected(demo_client):
    crlf = bytes([13, 10])

    def chunks():  # a well-formed multipart upload whose file just keeps going
        yield (b"--xyz" + crlf
               + b'Content-Disposition: form-data; name="files"; filename="big.jpg"' + crlf
               + b"Content-Type: image/jpeg" + crlf + crlf + bytes([0xFF, 0xD8, 0xFF, 0xE0]))
        block = b"x" * (1024 * 1024)
        for _ in range(MAX_BODY // len(block) + 2):
            yield block
        yield crlf + b"--xyz--" + crlf

    r = demo_client.post("/api/v1/services", content=chunks(),
                         headers={"Content-Type": "multipart/form-data; boundary=xyz"})
    assert r.status_code == 413


# 5: nobody can lock you out from another device by typing your email
def test_lockout_is_per_device_and_email(db, user):
    app.dependency_overrides[get_db] = lambda: db
    attacker = TestClient(app, client=("10.0.0.66", 5555))
    owner = TestClient(app, client=("10.0.0.2", 5555))
    for _ in range(auth.FREE_ATTEMPTS + 3):
        attacker.post("/api/v1/auth/login", json={"email": "me@example.com", "password": "guessing-1"})
    assert attacker.post("/api/v1/auth/login", json={"email": "me@example.com",
                                                     "password": PASSWORD}).status_code == 429
    assert owner.post("/api/v1/auth/login", json={"email": "me@example.com",
                                                  "password": PASSWORD}).status_code == 200
    # one device spraying many emails still hits the per-device limit
    for i in range(auth.FREE_ATTEMPTS_PER_DEVICE):
        attacker.post("/api/v1/auth/login", json={"email": f"user{i}@example.com", "password": "x"})
    assert attacker.post("/api/v1/auth/login", json={"email": "new@example.com", "password": "x"}).status_code == 429
    app.dependency_overrides.clear()


# 6: invites are claimed atomically; a failed sign-up gives the invite back
def test_failed_signup_releases_the_invite(db, user):
    owner = signed_in(db)
    token = owner.post("/api/v1/auth/invites").json()["link"].split("invite=")[1]
    guest = TestClient(app)
    taken = {"name": "X", "email": "me@example.com", "password": PASSWORD, "invite": token}
    assert guest.post("/api/v1/auth/signup", json=taken).status_code == 409
    ok = guest.post("/api/v1/auth/signup", json={**taken, "email": "new@example.com"})
    assert ok.status_code == 201
    assert guest.post("/api/v1/auth/signup", json={**taken, "email": "third@example.com"}).status_code == 403
    inv = db.scalar(select(m.Invite))
    assert inv.used_by == ok.json()["user"]["id"]
    app.dependency_overrides.clear()


# 7: behind a proxy that rewrites Host, writes from a listed host name still work
def test_origin_matching_allowed_host_works_behind_host_rewriting_proxy(db, user, monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "localhost,127.0.0.1,cars.example.com")
    app.dependency_overrides[get_db] = lambda: db
    behind_proxy = TestClient(app, base_url="http://127.0.0.1:8000")  # nginx sends Host: 127.0.0.1:8000
    r = behind_proxy.post("/api/v1/auth/login", json={"email": "me@example.com", "password": PASSWORD},
                          headers={"Origin": "https://cars.example.com"})
    assert r.status_code == 200
    evil = behind_proxy.post("/api/v1/vehicles", json={"nickname": "x", "make": "a", "model": "b", "year": 2020},
                             headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    app.dependency_overrides.clear()


# 8: the signing key is read once
def test_signing_key_is_cached(db, user, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secret_key", "")
    c = signed_in(db)
    (tmp_path / "secret_key").unlink()  # gone from disk: sessions keep working from the cache
    assert c.get("/api/v1/vehicles").status_code == 200
    app.dependency_overrides.clear()


# ---------- fixtures ----------

import pytest  # noqa: E402


@pytest.fixture
def anon_db_with_orphan(db):
    """A database from before accounts: a vehicle with an overdue oil change and no owner."""
    v = m.Vehicle(nickname="civic", make="Honda", model="Civic", year=2020)
    db.add(v)
    db.flush()
    oil = db.scalar(select(m.ServiceType).where(m.ServiceType.key == "oil"))
    db.add(m.ReminderRule(vehicle_id=v.id, service_type_id=oil.id, interval_months=6,
                          baseline_date=TODAY - dt.timedelta(days=400)))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    yield db, TestClient(app)
    app.dependency_overrides.clear()
