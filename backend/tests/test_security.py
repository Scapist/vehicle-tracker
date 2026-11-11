"""Guards for running without a login on a home network."""
import logging

from fastapi.testclient import TestClient

from app.main import app
from app.notify import factory
from app.security import MAX_BODY, RedactingFormatter
from tests.conftest import TODAY

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


def test_unknown_host_is_rejected_dns_rebinding(demo_client):
    rebound = TestClient(app, base_url="http://evil.example")
    assert rebound.get("/api/v1/vehicles").status_code == 400
    assert rebound.get("/api/v1/export/services.csv").status_code == 400
    assert demo_client.get("/api/v1/vehicles").status_code == 200


def test_cross_site_writes_blocked_same_site_allowed(demo_client):
    rid = demo_client.get("/api/v1/vehicles/1/rules").json()[0]["id"]
    evil = {"Origin": "https://evil.example"}
    assert demo_client.post(f"/api/v1/rules/{rid}/done", headers=evil).status_code == 403
    assert demo_client.post(f"/api/v1/rules/{rid}/snooze", headers={"Origin": "null"}).status_code == 403
    form = demo_client.post("/api/v1/services", headers={"Sec-Fetch-Site": "cross-site"},
                            data={"vehicle_id": 1, "date": TODAY.isoformat()})
    assert form.status_code == 403
    # reads are unaffected; the app's own pages are allowed
    assert demo_client.get("/api/v1/vehicles", headers=evil).status_code == 200
    same = demo_client.post(f"/api/v1/rules/{rid}/snooze", headers={"Origin": "http://testserver",
                                                                    "Sec-Fetch-Site": "same-origin"})
    assert same.status_code == 204
    # no Origin and no fetch metadata (curl, the bot's own HTTP) still works
    assert demo_client.post("/api/v1/vehicles/1/odometer", json={"km": 84600}).status_code == 201


def test_oversized_request_rejected_before_reading(demo_client):
    r = demo_client.post("/api/v1/services", headers={"Content-Length": str(MAX_BODY + 1)}, content=b"x")
    assert r.status_code == 413


def test_upload_limits(demo_client, monkeypatch):
    from app.services import records

    monkeypatch.setattr(records, "MAX_UPLOAD", 200)
    big = JPEG + b"0" * 500
    r = demo_client.post("/api/v1/services", data={"vehicle_id": 1, "date": TODAY.isoformat()},
                         files=[("files", ("big.jpg", big, "image/jpeg"))])
    assert r.status_code == 422
    many = [("files", (f"r{i}.jpg", JPEG, "image/jpeg")) for i in range(11)]
    r = demo_client.post("/api/v1/services", data={"vehicle_id": 1, "date": TODAY.isoformat()}, files=many)
    assert r.status_code == 422 and "at most 10" in r.json()["detail"]


def test_security_headers_and_image_csp(demo_client):
    r = demo_client.post("/api/v1/services", data={"vehicle_id": 1, "date": TODAY.isoformat()},
                         files=[("files", ("r.jpg", JPEG, "image/jpeg"))])
    att = r.json()["attachments"][0]["id"]
    got = demo_client.get(f"/api/v1/attachments/{att}")
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in got.headers["content-security-policy"]
    assert demo_client.get("/healthz").headers["x-frame-options"] == "SAMEORIGIN"


def test_csv_tab_and_cr_prefixed_formulas_neutralised(demo_client, demo):
    from sqlalchemy import select

    from app import models as m

    rec = demo.scalar(select(m.ServiceRecord))
    rec.vendor = chr(9) + "=cmd|' /C calc'!A0"
    rec.notes = chr(13) + "+1"
    demo.commit()
    text = demo_client.get("/api/v1/export/services.csv").text
    assert "'" + chr(9) + "=cmd" in text and "'" + chr(13) + "+1" in text


def test_vehicle_field_lengths(client):
    long = {"nickname": "x" * 61, "make": "a", "model": "b", "year": 2020}
    assert client.post("/api/v1/vehicles", json=long).status_code == 422
    assert client.post("/api/v1/vehicles", json={**long, "nickname": "ok", "year": 3000}).status_code == 422


def test_bad_chat_id_entry_does_not_crash(monkeypatch):
    monkeypatch.setattr(factory.settings, "telegram_allowed_chat_ids", "123, oops, 456")
    assert factory.allowed_chat_ids() == [123, 456]


def test_log_lines_redact_bot_token():
    fmt = RedactingFormatter("%(message)s")
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1,
                            "POST https://api.telegram.org/bot123456789:FAKEtokenFAKEtokenFAKEtoken_abc-12/getMe",
                            None, None)
    out = fmt.format(rec)
    assert "FAKEtoken" not in out and "<redacted>" in out
