"""Fixes from the full-codebase review before going public."""
import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app import models as m
from app.bot import logic
from app.db import get_db
from app.evaluator import evaluate
from app.main import app
from tests.conftest import PASSWORD, TODAY


def _outbox(db):
    return db.scalars(select(m.NotificationOutbox)).all()


def test_recreated_item_with_a_reused_id_still_alerts(client, db, user):
    """SQLite reuses the highest id, so a deleted item's alert history must not carry over to a new one."""
    v = client.post("/api/v1/vehicles", json={"nickname": "civic", "make": "H", "model": "C", "year": 2020}).json()
    body = {"vehicle_id": v["id"], "kind": "insurance", "title": "Insurance", "due_date": str(TODAY), "soon_days": 30}
    first = client.post("/api/v1/date-items", json=body).json()
    evaluate(db)
    assert len(_outbox(db)) == 1
    assert client.delete(f"/api/v1/date-items/{first['id']}").status_code == 204
    second = client.post("/api/v1/date-items", json=body).json()
    assert second["id"] == first["id"]  # the situation the bug needed
    evaluate(db)
    assert len(_outbox(db)) == 1 and _outbox(db)[0].dedupe_key.startswith(f"date:{second['id']}|")


def test_a_correction_cannot_be_deleted_or_moved(client, db, user):
    v = client.post("/api/v1/vehicles", json={"nickname": "civic", "make": "H", "model": "C", "year": 2020}).json()
    client.post(f"/api/v1/vehicles/{v['id']}/odometer", json={"km": 50_000})
    corr = client.post(f"/api/v1/vehicles/{v['id']}/odometer", json={"km": 40_000, "is_correction": True}).json()
    assert client.delete(f"/api/v1/vehicles/{v['id']}/odometer/{corr['id']}").status_code == 409
    reply = logic.log_km(db, user, v["id"], 39_000, confirmed=False, correction=True)
    assert reply.buttons == []  # no "Wrong vehicle" undo for a correction
    assert "can't be moved" in logic.handle_callback(db, user, f"wrong:{corr['id']}").text


def test_odd_input_is_rejected_not_a_crash(db, user):
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        r = c.post("/api/v1/auth/setup", json={"name": "X", "email": "x@example.com", "password": PASSWORD,
                                               "setup_code": "ÉÉÉÉ"})
        assert r.status_code in (403, 409)  # not 500 (an account exists already, or the code is wrong)
        assert auth.parse_token("1.1.9999999999.é") is None  # used to raise TypeError inside the request guard
        c.post("/api/v1/auth/login", json={"email": "me@example.com", "password": PASSWORD})
        v = c.post("/api/v1/vehicles", json={"nickname": "civic", "make": "H", "model": "C", "year": 2020}).json()
        big = c.post("/api/v1/services", data={"vehicle_id": v["id"], "date": str(TODAY),
                                               "odometer_km": 10**20, "cost_cents": 0})
        assert big.status_code == 422
        inf = c.post("/api/v1/services", data={"vehicle_id": v["id"], "date": str(TODAY), "cost_cents": 100,
                                               "item_costs": '{"1": Infinity}'})
        assert inf.status_code == 422
        rule = c.post(f"/api/v1/vehicles/{v['id']}/rules", json={"service_type_id": 1, "interval_km": 10**19})
        assert rule.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_deleting_a_service_removes_its_files(client, db, user):
    v = client.post("/api/v1/vehicles", json={"nickname": "civic", "make": "H", "model": "C", "year": 2020}).json()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    rec = client.post("/api/v1/services", data={"vehicle_id": v["id"], "date": str(TODAY - dt.timedelta(days=1))},
                      files=[("files", ("r.png", png, "image/png"))]).json()
    from app.services import records
    path = records.attachment_path(db.scalar(select(m.Attachment)))
    assert path.exists()
    assert client.delete(f"/api/v1/services/{rec['id']}").status_code == 204
    assert not path.exists() and db.scalar(select(m.Attachment)) is None
