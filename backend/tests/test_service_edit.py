import datetime as dt

from sqlalchemy import select

from app import models as m
from app.services import odometer, records
from tests.conftest import TODAY

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
API = "/api/v1"


def _log(client, **extra):
    data = {"vehicle_id": 1, "date": (TODAY - dt.timedelta(days=3)).isoformat(), "cost_cents": 10_000,
            "type_ids": [1, 2], "item_costs": '{"1": 6000, "2": 4000}', **extra}
    r = client.post(f"{API}/services", data=data, files=[("files", ("r.jpg", JPEG, "image/jpeg"))])
    assert r.status_code == 201, r.text
    return r.json()


def test_edit_a_service(demo_client, demo):
    svc = _log(demo_client, vendor="Jiffy")
    r = demo_client.patch(f"{API}/services/{svc['id']}", json={"vendor": "Speedy", "notes": "synthetic"})
    assert r.status_code == 200
    out = r.json()
    assert out["vendor"] == "Speedy" and out["notes"] == "synthetic"
    assert out["cost_cents"] == 10_000 and len(out["items"]) == 2  # untouched fields stay

    # drop a type: the remaining one keeps its split cost
    out = demo_client.patch(f"{API}/services/{svc['id']}", json={"type_ids": [1]}).json()
    assert [(i["service_type_id"], i["cost_cents"]) for i in out["items"]] == [(1, 6000)]
    # lower the total below the split: the split is cleared rather than left inconsistent
    out = demo_client.patch(f"{API}/services/{svc['id']}", json={"cost_cents": 5000}).json()
    assert out["cost_cents"] == 5000 and out["items"][0]["cost_cents"] is None
    # clearing optional fields
    out = demo_client.patch(f"{API}/services/{svc['id']}", json={"vendor": "", "odometer_km": None}).json()
    assert out["vendor"] is None and out["odometer_km"] is None


def test_edit_validates(demo_client):
    svc = _log(demo_client)
    future = (TODAY + dt.timedelta(days=1)).isoformat()
    assert demo_client.patch(f"{API}/services/{svc['id']}", json={"date": future}).status_code == 422
    assert demo_client.patch(f"{API}/services/{svc['id']}", json={"type_ids": [99_999]}).status_code == 422
    assert demo_client.patch(f"{API}/services/{svc['id']}", json={"cost_cents": -1}).status_code == 422


def test_edit_higher_odometer_counts_as_reading(demo_client, demo):
    svc = _log(demo_client, date=TODAY.isoformat())
    cur = odometer.current_km(demo, 1)
    demo_client.patch(f"{API}/services/{svc['id']}", json={"odometer_km": cur + 100})
    assert odometer.current_km(demo, 1) == cur + 100
    # a lower km just corrects the record, without touching the odometer
    demo_client.patch(f"{API}/services/{svc['id']}", json={"odometer_km": 10})
    assert odometer.current_km(demo, 1) == cur + 100


def test_delete_service_and_receipts(demo_client, demo):
    svc = _log(demo_client)
    att = demo.get(m.Attachment, svc["attachments"][0]["id"])
    path = records.attachment_path(att)
    assert demo_client.delete(f"{API}/attachments/{att.id}").status_code == 204
    assert not path.exists()
    assert demo_client.get(f"{API}/services/{svc['id']}").json()["attachments"] == []

    svc = _log(demo_client)
    path = records.attachment_path(demo.get(m.Attachment, svc["attachments"][0]["id"]))
    path.unlink()  # a file already missing from disk must not block the delete
    assert demo_client.delete(f"{API}/services/{svc['id']}").status_code == 204
    assert demo_client.get(f"{API}/services/{svc['id']}").status_code == 404


def test_winter_tire_dates_only_once_per_vehicle(demo_client, demo):
    for row in demo.scalars(select(m.DateItem).where(m.DateItem.kind.in_(("winter_install", "winter_remove")))):
        demo.delete(row)
    demo.commit()
    body = {"vehicle_id": 1, "kind": "winter_install", "title": "Install winter tires by Dec 1",
            "due_date": "2026-12-01", "recurs_yearly": True}
    assert demo_client.post(f"{API}/date-items", json=body).status_code == 201
    assert demo_client.post(f"{API}/date-items", json=body).status_code == 409
    other_kind = {**body, "kind": "winter_remove", "due_date": "2027-03-15"}
    assert demo_client.post(f"{API}/date-items", json=other_kind).status_code == 201
    custom = {**body, "kind": "custom", "title": "Inspection"}  # other kinds can repeat
    assert demo_client.post(f"{API}/date-items", json=custom).status_code == 201
    assert demo_client.post(f"{API}/date-items", json=custom).status_code == 201
