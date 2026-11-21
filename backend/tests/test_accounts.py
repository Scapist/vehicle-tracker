import datetime as dt

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app import models as m
from app.bot import logic, runner
from app.config import settings
from app.db import get_db
from app.evaluator import evaluate, resolve_recipient
from app.main import app
from app.notify.base import TelegramNotifier
from tests.conftest import CHAT_ID, NOW, PASSWORD, TODAY, make_user, signed_in

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture
def anon(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def new_account(name="Sam", email="sam@example.com", password=PASSWORD, **extra):
    return {"name": name, "email": email, "password": password, **extra}


# ---------- first-run setup ----------

def test_setup_needs_code_creates_owner_and_claims_existing_data(anon, db, monkeypatch):
    old = m.Vehicle(nickname="civic", make="Honda", model="Civic", year=2026)  # from before accounts
    db.add_all([old, m.DateItem(kind="custom", title="Old", due_date=TODAY)])
    db.commit()
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "5550001234")
    me = anon.get("/api/v1/auth/me").json()
    assert me["user"] is None and me["setup_required"] is True
    code = auth.ensure_setup_code()

    bad = anon.post("/api/v1/auth/setup", json=new_account(setup_code="WRONG123"))
    assert bad.status_code == 403
    r = anon.post("/api/v1/auth/setup", json=new_account(setup_code=code.lower()))
    assert r.status_code == 201, r.text
    me = r.json()["user"]
    assert me["is_owner"] and me["email"] == "sam@example.com" and me["telegram_linked"]  # legacy chat carried over
    assert [v["nickname"] for v in anon.get("/api/v1/vehicles").json()] == ["civic"]
    assert db.scalar(select(m.DateItem)).user_id == me["id"]
    # one owner only; the code is single-use
    again = anon.post("/api/v1/auth/setup", json=new_account(email="x@example.com", setup_code=code))
    assert again.status_code == 409


def test_setup_and_signup_validate_input(anon):
    code = auth.ensure_setup_code()
    for body, why in [(new_account(password="short", setup_code=code), "password too short"),
                      (new_account(email="not-an-email", setup_code=code), "bad email"),
                      (new_account(name="   ", setup_code=code), "blank name")]:
        assert anon.post("/api/v1/auth/setup", json=body).status_code == 422, why


def test_setup_code_guessing_is_locked_out(anon):
    auth.ensure_setup_code()
    for _ in range(auth.FREE_ATTEMPTS):
        anon.post("/api/v1/auth/setup", json=new_account(setup_code="NOPE0000"))
    r = anon.post("/api/v1/auth/setup", json=new_account(setup_code=auth.ensure_setup_code()))
    assert r.status_code == 429


# ---------- login, sessions ----------

def test_login_wrong_password_unknown_email_and_lockout(anon, user):
    assert anon.post("/api/v1/auth/login", json={"email": "me@example.com", "password": "nope-nope-1"}).json() \
        == anon.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "x"}).json() \
        == {"detail": "Wrong email or password"}
    for _ in range(auth.FREE_ATTEMPTS):
        anon.post("/api/v1/auth/login", json={"email": "ME@example.com ", "password": "nope-nope-1"})
    assert anon.post("/api/v1/auth/login", json={"email": "me@example.com", "password": PASSWORD}).status_code == 429
    with time_machine.travel(NOW + dt.timedelta(minutes=5), tick=False):
        ok = anon.post("/api/v1/auth/login", json={"email": "Me@Example.com", "password": PASSWORD})
        assert ok.status_code == 200 and ok.json()["user"]["name"] == "Me"


def test_session_cookie_flags_and_logout(anon, user):
    r = anon.post("/api/v1/auth/login", json={"email": "me@example.com", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=2592000" in cookie
    assert anon.get("/api/v1/vehicles").status_code == 200
    anon.post("/api/v1/auth/logout")
    assert anon.get("/api/v1/vehicles").status_code == 401


def test_tampered_and_expired_sessions_rejected(anon, user):
    anon.post("/api/v1/auth/login", json={"email": "me@example.com", "password": PASSWORD})
    good = anon.cookies.get(auth.COOKIE)
    uid, ver, exp, sig = good.split(".")
    for forged in (f"{int(uid) + 1}.{ver}.{exp}.{sig}", f"{uid}.{ver}.{int(exp) + 999}.{sig}", "garbage"):
        anon.cookies.clear()
        anon.cookies.set(auth.COOKIE, forged)
        assert anon.get("/api/v1/vehicles").status_code == 401, forged
    anon.cookies.clear()
    anon.cookies.set(auth.COOKIE, good)
    assert anon.get("/api/v1/vehicles").status_code == 200
    with time_machine.travel(NOW + dt.timedelta(days=31), tick=False):
        assert anon.get("/api/v1/vehicles").status_code == 401


def test_change_password_signs_out_other_devices_only(db, user):
    phone, laptop = signed_in(db), signed_in(db)
    assert laptop.post("/api/v1/auth/password", json={"current_password": "wrong-wrong",
                                                      "new_password": "another-pass-2"}).status_code == 403
    assert laptop.post("/api/v1/auth/password", json={"current_password": PASSWORD,
                                                      "new_password": "another-pass-2"}).status_code == 204
    assert laptop.get("/api/v1/vehicles").status_code == 200
    assert phone.get("/api/v1/vehicles").status_code == 401
    assert phone.post("/api/v1/auth/login", json={"email": "me@example.com",
                                                  "password": "another-pass-2"}).status_code == 200
    app.dependency_overrides.clear()


def test_logout_everywhere(db, user):
    a, b = signed_in(db), signed_in(db)
    assert a.post("/api/v1/auth/logout-everywhere").status_code == 204
    assert a.get("/api/v1/vehicles").status_code == 401 and b.get("/api/v1/vehicles").status_code == 401
    app.dependency_overrides.clear()


def test_data_endpoints_need_a_session(anon, user):
    for path in ("/api/v1/vehicles", "/api/v1/attachments/1", "/api/v1/export/services.csv", "/api/v1/status",
                 "/api/v1/service-types", "/docs", "/openapi.json", "/api/v1/auth/invites"):
        assert anon.get(path).status_code == 401, path
    assert anon.get("/healthz").status_code == 200
    me = anon.get("/api/v1/auth/me").json()
    assert me["user"] is None and me["setup_required"] is False


# ---------- invites ----------

def test_invite_signup_single_use_and_expiry(anon, db, user):
    owner = signed_in(db)
    inv = owner.post("/api/v1/auth/invites").json()
    token = inv["link"].split("invite=")[1]
    assert owner.get("/api/v1/auth/invites").json()[0]["used"] is False

    assert anon.post("/api/v1/auth/signup", json=new_account(invite="made-up")).status_code == 403
    r = anon.post("/api/v1/auth/signup", json=new_account(invite=token))
    assert r.status_code == 201 and r.json()["user"]["is_owner"] is False
    assert anon.post("/api/v1/auth/signup", json=new_account(email="t@example.com", invite=token)).status_code == 403
    assert owner.get("/api/v1/auth/invites").json()[0]["used_by_name"] == "Sam"

    late = owner.post("/api/v1/auth/invites").json()["link"].split("invite=")[1]
    with time_machine.travel(NOW + dt.timedelta(days=8), tick=False):
        assert anon.post("/api/v1/auth/signup", json=new_account(email="u@example.com", invite=late)).status_code == 403
    app.dependency_overrides.clear()


def test_duplicate_email_and_revoke(anon, db, user):
    owner = signed_in(db)
    token = owner.post("/api/v1/auth/invites").json()["link"].split("invite=")[1]
    assert anon.post("/api/v1/auth/signup", json=new_account(email="me@example.com", invite=token)).status_code == 409
    inv_id = owner.get("/api/v1/auth/invites").json()[0]["id"]
    assert owner.delete(f"/api/v1/auth/invites/{inv_id}").status_code == 204
    assert anon.post("/api/v1/auth/signup", json=new_account(invite=token)).status_code == 403
    app.dependency_overrides.clear()


def test_only_the_owner_manages_invites_and_users(db, user):
    make_user(db, "sam@example.com", "Sam", owner=False, chat_id=None)
    sam = signed_in(db, "sam@example.com")
    assert sam.post("/api/v1/auth/invites").status_code == 403
    assert sam.get("/api/v1/auth/users").status_code == 403
    owner = signed_in(db)
    assert [u["name"] for u in owner.get("/api/v1/auth/users").json()] == ["Me", "Sam"]
    app.dependency_overrides.clear()


# ---------- isolation ----------

@pytest.fixture
def two_users(demo_client, demo):
    """'me' owns the demo Civic (+ a receipt); 'sam' is a second account with nothing."""
    up = demo_client.post("/api/v1/services", data={"vehicle_id": 1, "date": TODAY.isoformat()},
                          files=[("files", ("r.jpg", JPEG, "image/jpeg"))])
    att = up.json()["attachments"][0]["id"]
    make_user(demo, "sam@example.com", "Sam", owner=False, chat_id=222)
    sam = signed_in(demo, "sam@example.com")
    yield sam, att
    app.dependency_overrides.clear()


def test_other_users_data_is_invisible_everywhere(two_users, demo):
    sam, att = two_users
    rule = demo.scalar(select(m.ReminderRule)).id
    date_item = demo.scalar(select(m.DateItem)).id
    tire = demo.scalar(select(m.TireSet)).id
    service = demo.scalar(select(m.ServiceRecord)).id
    assert sam.get("/api/v1/vehicles").json() == []
    assert sam.get("/api/v1/tire-sets").json() == []
    assert sam.get("/api/v1/date-items").json() == []
    assert sam.get("/api/v1/status").json() == []
    assert sam.get("/api/v1/reports").json() == {"years": [], "categories": []}
    assert "Jiffy" not in sam.get("/api/v1/export/services.csv").text
    not_found = [
        ("get", "/api/v1/vehicles/1", None), ("get", "/api/v1/vehicles/1/dashboard", None),
        ("get", "/api/v1/vehicles/1/odometer", None), ("get", "/api/v1/vehicles/1/services", None),
        ("get", "/api/v1/vehicles/1/rules", None), ("get", f"/api/v1/attachments/{att}", None),
        ("get", "/api/v1/reports?vehicle=1", None), ("get", "/api/v1/export/odometer.csv?vehicle=1", None),
        ("patch", "/api/v1/vehicles/1", {"nickname": "mine now"}),
        ("post", "/api/v1/vehicles/1/odometer", {"km": 999999}),
        ("post", "/api/v1/vehicles/1/rules", {"service_type_id": 6, "interval_months": 12}),
        ("patch", f"/api/v1/rules/{rule}", {"enabled": False}), ("post", f"/api/v1/rules/{rule}/done", None),
        ("post", f"/api/v1/rules/{rule}/snooze", None), ("delete", f"/api/v1/rules/{rule}", None),
        ("delete", f"/api/v1/date-items/{date_item}", None), ("post", f"/api/v1/date-items/{date_item}/done", None),
        ("post", "/api/v1/date-items", {"vehicle_id": 1, "title": "x", "due_date": "2027-01-01"}),
        ("post", f"/api/v1/tire-sets/{tire}/mount", None), ("patch", f"/api/v1/tire-sets/{tire}", {"label": "x"}),
        ("post", f"/api/v1/tire-sets/{tire}/tread", {"depth_mm": 2}),
        ("post", "/api/v1/tire-sets", {"vehicle_id": 1, "label": "x", "season": "winter"}),
        ("delete", f"/api/v1/services/{service}", None),
    ]
    for method, path, body in not_found:
        r = getattr(sam, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, path, r.status_code)
    r = sam.post("/api/v1/services", data={"vehicle_id": 1, "date": TODAY.isoformat()})
    assert r.status_code == 404
    r = sam.post(f"/api/v1/services/{service}/attachments", files={"file": ("r.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 404
    # nothing changed for the real owner
    assert demo.get(m.Vehicle, 1).nickname == "Civic" and demo.get(m.ReminderRule, rule).enabled


def test_nicknames_are_unique_per_user_not_globally(two_users):
    sam, _ = two_users
    body = {"nickname": "Civic", "make": "Honda", "model": "Civic", "year": 2020}
    assert sam.post("/api/v1/vehicles", json=body).status_code == 201
    assert sam.post("/api/v1/vehicles", json=body).status_code == 409


def test_bot_buttons_cannot_touch_other_users_data(two_users, demo):
    sam_user = demo.scalar(select(m.User).where(m.User.email == "sam@example.com"))
    rule = demo.scalar(select(m.ReminderRule))
    reading = demo.scalar(select(m.OdometerReading))
    service = demo.scalar(select(m.ServiceRecord))
    assert "No vehicles" in logic.handle_text(demo, sam_user, "84600").text
    for data in (f"done:rule:{rule.id}", f"km:1:90000", f"corr:1:10", f"ok:1:90000", f"wrong:{reading.id}",
                 f"undo:{service.id}", f"snooze:rule:{rule.id}:7", f"rmove:{service.id}:1"):
        reply = logic.handle_callback(demo, sam_user, data)
        assert "Logged" not in reply.text and "Snoozed" not in reply.text and "Moved" not in reply.text, data
    assert demo.get(m.OdometerReading, reading.id) is not None
    assert demo.get(m.ServiceRecord, service.id) is not None
    assert "84,500" not in logic.cmd_vehicles(demo, sam_user).text


# ---------- Telegram ----------

def test_telegram_link_code_flow(db, user):
    make_user(db, "sam@example.com", "Sam", owner=False, chat_id=None)
    sam = signed_in(db, "sam@example.com")
    code = sam.post("/api/v1/auth/telegram/link-code").json()["code"]
    assert "wrong or expired" in logic.cmd_link(db, 999, "ZZZZZZZZ").text
    assert "Linked to Sam" in logic.cmd_link(db, 999, code.lower()).text
    assert logic.user_for_chat(db, 999).email == "sam@example.com"
    assert "wrong or expired" in logic.cmd_link(db, 999, code).text  # single use
    # moving a chat to another account unlinks it from the first
    code2 = signed_in(db).post("/api/v1/auth/telegram/link-code").json()["code"]
    logic.cmd_link(db, 999, code2)
    assert logic.user_for_chat(db, 999).email == "me@example.com"
    assert db.scalar(select(m.User).where(m.User.email == "sam@example.com")).telegram_chat_id is None
    late = sam.post("/api/v1/auth/telegram/link-code").json()["code"]
    with time_machine.travel(NOW + dt.timedelta(minutes=11), tick=False):
        assert "wrong or expired" in logic.cmd_link(db, 999, late).text  # codes last 10 minutes
    app.dependency_overrides.clear()


def test_link_attempts_are_rate_limited():
    logic._link_attempts.clear()
    assert all(runner.link_allowed(42, now=1000 + i) for i in range(runner.LINK_ATTEMPTS))
    assert not runner.link_allowed(42, now=1010)
    assert runner.link_allowed(42, now=1000 + runner.LINK_WINDOW + 20)


def test_alerts_go_to_each_owners_chat_only(demo, user):
    sam = make_user(demo, "sam@example.com", "Sam", owner=False, chat_id=None)
    demo.add(m.Vehicle(nickname="Van", make="Ford", model="Transit", year=2010, user_id=sam.id))
    demo.add(m.DateItem(user_id=sam.id, kind="custom", title="Sam's inspection", due_date=TODAY))
    demo.commit()
    evaluate(demo)
    rows = demo.scalars(select(m.NotificationOutbox)).all()
    mine = [r for r in rows if r.title.startswith("Civic")]
    sams = [r for r in rows if "Sam's" in r.title]
    assert mine and all(r.recipient == f"user:{user.id}" for r in mine)
    assert sams and all(r.recipient == f"user:{sam.id}" for r in sams)
    # the chat is looked up when sending: mine resolves, Sam's (not linked) is held
    assert resolve_recipient(demo, f"user:{user.id}") == f"telegram:{CHAT_ID}"
    assert resolve_recipient(demo, f"user:{sam.id}") is None

    sent = []

    class FakeClient:
        def post(self, url, json):
            sent.append(json["chat_id"])
            return type("R", (), {"raise_for_status": lambda self: None})()

    tg = TelegramNotifier("1:x", client=FakeClient())
    with pytest.raises(ValueError):
        tg.send("t", "b", recipient=None)  # never a silent "success"
    tg.send("t", "b", recipient=f"telegram:{CHAT_ID}")
    tg.send("t", "b", recipient=str(CHAT_ID))  # rows queued before chat apps had a prefix
    assert sent == [CHAT_ID, CHAT_ID]  # no default chat: never someone else's
