import json

from sqlalchemy import select

from app import models as m
from app.config import settings
from tests.conftest import TODAY

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PDF = b"%PDF-1.4 test"


def test_dashboard_shape(demo_client):
    r = demo_client.get("/api/v1/vehicles/1/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert d["vehicle"]["current_km"] == 84500
    titles = {i["title"]: i for i in d["items"]}
    assert titles["Oil change"]["status"] == "overdue"  # last 76,000 + 8,000 = 84,000 < 84,500
    assert titles["Brake inspection"]["status"] == "overdue"  # baseline 62,000 + 20,000
    assert d["items"][0]["status"] == "overdue"
    assert d["km_per_day"] and 30 < d["km_per_day"] < 50
    assert d["mounted_tire_set"]["label"] == "Summer set"
    assert d["year_cost_cents"] == 8900 + 4500


def test_vehicle_crud_and_duplicate_nickname(client):
    body = {"nickname": "Bike", "make": "Honda", "model": "CB", "year": 2020}
    assert client.post("/api/v1/vehicles", json=body).status_code == 201
    assert client.post("/api/v1/vehicles", json=body).status_code == 409
    assert client.get("/api/v1/vehicles").json()[0]["nickname"] == "Bike"


def test_odometer_backwards_rejected_then_correction(demo_client):
    c = demo_client
    r = c.post("/api/v1/vehicles/1/odometer", json={"km": 80000})
    assert r.status_code == 422 and "correction" in r.json()["detail"]
    r = c.post("/api/v1/vehicles/1/odometer", json={"km": 84600})
    assert r.status_code == 201
    r = c.post("/api/v1/vehicles/1/odometer", json={"km": 84000, "is_correction": True})
    assert r.status_code == 201
    assert c.get("/api/v1/vehicles/1").json()["current_km"] == 84000
    hist = c.get("/api/v1/vehicles/1/odometer").json()
    assert any(h["invalidated"] for h in hist)  # 84,500 and 84,600 were invalidated


def test_service_with_receipt(demo_client, tmp_path):
    types = {t["key"]: t["id"] for t in demo_client.get("/api/v1/service-types").json()}
    r = demo_client.post("/api/v1/services", data={
        "vehicle_id": 1, "date": TODAY.isoformat(), "odometer_km": 84700, "cost_cents": 9000,
        "vendor": "Shop", "type_ids": [types["oil"]],
    }, files=[("files", ("r.jpg", JPEG, "image/jpeg")), ("files", ("r.pdf", PDF, "application/pdf"))])
    assert r.status_code == 201, r.text
    rec = r.json()
    assert len(rec["attachments"]) == 2 and rec["type_names"] == ["Oil change"]
    stored = list((tmp_path / "receipts" / str(TODAY.year)).iterdir())
    assert len(stored) == 2
    got = demo_client.get(f"/api/v1/attachments/{rec['attachments'][0]['id']}")
    assert got.status_code == 200 and got.content in (JPEG, PDF)
    # service reading moved current km; the oil rule has a new cycle and is now ok
    d = demo_client.get("/api/v1/vehicles/1/dashboard").json()
    assert d["vehicle"]["current_km"] == 84700
    assert {i["title"]: i["status"] for i in d["items"]}["Oil change"] == "ok"


def test_upload_rejects_wrong_type(demo_client):
    r = demo_client.post("/api/v1/services", data={"vehicle_id": 1, "date": TODAY.isoformat()},
                         files=[("files", ("x.exe", b"MZ\x90\x00", "application/octet-stream"))])
    assert r.status_code == 422
    assert demo_client.get("/api/v1/vehicles/1/services").json()[0]["date"] != TODAY.isoformat()


def test_rule_validation_and_done(demo_client):
    c = demo_client
    assert c.post("/api/v1/vehicles/1/rules", json={"service_type_id": 6}).status_code == 422
    r = c.post("/api/v1/vehicles/1/rules", json={"service_type_id": 6, "interval_months": 48,
                                                  "baseline_date": "2025-01-01"})
    assert r.status_code == 201
    # a rule with neither interval can't be made by patching either
    assert c.patch(f"/api/v1/rules/{r.json()['id']}", json={"interval_months": None}).status_code == 422
    rule_id = db_rule_id(demo_client, "oil")
    done = c.post(f"/api/v1/rules/{rule_id}/done")
    assert done.status_code == 201 and done.json()["odometer_km"] == 84500


def db_rule_id(client, key):
    types = {t["key"]: t["id"] for t in client.get("/api/v1/service-types").json()}
    rules = client.get("/api/v1/vehicles/1/rules").json()
    return next(r["id"] for r in rules if r["service_type_id"] == types[key])


def test_date_item_done_rolls_forward(demo_client, demo):
    items = demo_client.get("/api/v1/date-items", params={"vehicle_id": 1}).json()
    reg = next(i for i in items if i["kind"] == "registration")
    r = demo_client.post(f"/api/v1/date-items/{reg['id']}/done")
    assert r.json()["due_date"] == f"{int(reg['due_date'][:4]) + 1}{reg['due_date'][4:]}"


def test_winter_install_done_mounts_set_and_only_one_mounted(demo_client, demo):
    c = demo_client
    sets = {t["label"]: t for t in c.get("/api/v1/tire-sets").json()}
    assert sets["Summer set"]["mounted"] and not sets["Winter set"]["mounted"]
    item = next(i for i in c.get("/api/v1/date-items").json() if i["kind"] == "winter_install")
    r = c.post(f"/api/v1/date-items/{item['id']}/done", json={"tire_set_id": sets["Winter set"]["id"]})
    assert r.status_code == 200
    now = {t["label"]: t for t in c.get("/api/v1/tire-sets").json()}
    assert now["Winter set"]["mounted"] and not now["Summer set"]["mounted"]
    open_mounts = demo.scalars(select(m.TireMount).where(m.TireMount.removed_date.is_(None))).all()
    assert len(open_mounts) == 1
    assert c.post(f"/api/v1/tire-sets/{now['Winter set']['id']}/mount").status_code == 409  # already on


def test_tire_km_is_sum_of_mounts_and_tread_flag(demo_client):
    sets = {t["label"]: t for t in demo_client.get("/api/v1/tire-sets").json()}
    assert sets["Winter set"]["total_km"] == 77000 - 64000
    assert sets["Summer set"]["total_km"] == 84500 - 77000  # still mounted: counts to current km
    assert not sets["Winter set"]["tread_warning"]  # 4.5 mm is above the 4 mm winter threshold
    r = demo_client.post(f"/api/v1/tire-sets/{sets['Winter set']['id']}/tread", json={"depth_mm": 3.8})
    assert r.json()["tread_warning"]


def test_reports_allocation_and_csv(demo_client):
    rep = demo_client.get("/api/v1/reports", params={"vehicle": 1}).json()
    by_year = {r["year"]: r for r in rep["years"]}
    this_year = by_year[TODAY.year]
    # visit of 8900 with two unpriced items -> General; 4500 rotation -> single item takes it all
    assert this_year["by_category"]["General"] == 8900
    assert this_year["by_category"]["Tire rotation"] == 4500
    csv_text = demo_client.get("/api/v1/export/services.csv").text
    assert csv_text.splitlines()[0].startswith("vehicle,date,odometer_km")
    assert "Jiffy Lube" in csv_text


def test_status_feed(demo_client):
    feed = demo_client.get("/api/v1/status").json()
    assert feed and {"source", "subject", "title", "status", "due", "detail_url"} <= set(feed[0])


def test_unknown_api_path_404_not_spa(client):
    assert client.get("/api/v1/nope").status_code == 404


def test_item_costs_cannot_exceed_total(demo_client):
    r = demo_client.post("/api/v1/services", data={
        "vehicle_id": 1, "date": TODAY.isoformat(), "cost_cents": 100, "type_ids": [1],
        "item_costs": json.dumps({"1": 500})})
    assert r.status_code == 422
    assert settings.data_dir.exists()
