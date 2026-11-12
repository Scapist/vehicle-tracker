from sqlalchemy import select

from app import models as m
from tests.conftest import make_user, signed_in


def _types(client):
    return {t["name"]: t for t in client.get("/api/v1/service-types").json()}


def _vehicle(client):
    r = client.post("/api/v1/vehicles", json={"nickname": "civic", "make": "Honda", "model": "Civic", "year": 2020})
    return r.json()["id"]


def test_new_built_ins_are_there(client):
    names = _types(client)
    for n in ("Oil change", "Wheel alignment", "Transmission fluid", "Coolant", "Spark plugs", "Brake fluid",
              "Wiper blades"):
        assert n in names and names[n]["custom"] is False


def test_create_is_idempotent_by_name(client):
    r = client.post("/api/v1/service-types", json={"name": "  Rust   proofing "})
    assert r.status_code == 201
    t = r.json()
    assert t["name"] == "Rust proofing" and t["custom"] is True
    again = client.post("/api/v1/service-types", json={"name": "rust proofing"})
    assert again.status_code == 200 and again.json()["id"] == t["id"]
    # a built-in name gives the built-in back instead of a duplicate
    oil = client.post("/api/v1/service-types", json={"name": "OIL CHANGE"})
    assert oil.status_code == 200 and oil.json()["custom"] is False
    assert client.post("/api/v1/service-types", json={"name": "   "}).status_code == 422


def test_custom_types_are_private(db, client):
    mine = client.post("/api/v1/service-types", json={"name": "Detailing"}).json()
    make_user(db, email="other@example.com", owner=False, chat_id=222)
    other = signed_in(db, "other@example.com")
    assert "Detailing" not in _types(other)
    assert other.patch(f"/api/v1/service-types/{mine['id']}", json={"name": "x"}).status_code == 404
    assert other.delete(f"/api/v1/service-types/{mine['id']}").status_code == 404
    # nor can they log a service or add a reminder with it
    vid = _vehicle(other)
    r = other.post("/api/v1/services", data={"vehicle_id": vid, "type_ids": [mine["id"]], "cost_cents": "1000",
                                             "date": "2026-10-01"})
    assert r.status_code == 422
    r = other.post(f"/api/v1/vehicles/{vid}/rules", json={"service_type_id": mine["id"], "interval_months": 12})
    assert r.status_code == 422


def test_custom_type_works_for_services_rules_and_reports(client):
    vid = _vehicle(client)
    t = client.post("/api/v1/service-types", json={"name": "Detailing"}).json()
    r = client.post("/api/v1/services", data={"vehicle_id": vid, "type_ids": [t["id"]], "cost_cents": "12000",
                                              "date": "2026-10-01"})
    assert r.status_code == 201, r.text
    assert client.post(f"/api/v1/vehicles/{vid}/rules",
                       json={"service_type_id": t["id"], "interval_months": 6}).status_code == 201
    s = client.get("/api/v1/spending").json()
    assert s["by_category"] == {"Detailing": 12000}


def test_rename_and_delete_rules(client):
    a = client.post("/api/v1/service-types", json={"name": "Detailing"}).json()
    b = client.post("/api/v1/service-types", json={"name": "Wash"}).json()
    assert client.patch(f"/api/v1/service-types/{a['id']}", json={"name": "Full detail"}).json()["name"] == "Full detail"
    assert client.patch(f"/api/v1/service-types/{a['id']}", json={"name": "wash"}).status_code == 409
    oil = _types(client)["Oil change"]
    assert client.patch(f"/api/v1/service-types/{oil['id']}", json={"name": "x"}).status_code == 404  # built-in
    assert client.delete(f"/api/v1/service-types/{oil['id']}").status_code == 404
    # in use: only renaming is allowed, so history keeps its name
    vid = _vehicle(client)
    assert client.post("/api/v1/services", data={"vehicle_id": vid, "type_ids": [a["id"]], "date": "2026-10-01"}).status_code == 201
    assert client.delete(f"/api/v1/service-types/{a['id']}").status_code == 409
    assert client.delete(f"/api/v1/service-types/{b['id']}").status_code == 204
    assert "Wash" not in _types(client)


def test_deleting_an_account_removes_its_types(db, user, client):
    client.post("/api/v1/service-types", json={"name": "Detailing"})
    db.delete(user)
    db.commit()
    assert db.scalar(select(m.ServiceType).where(m.ServiceType.name == "Detailing")) is None


def test_single_service_is_owner_only(db, client):
    vid = _vehicle(client)
    sid = client.post("/api/v1/services", data={"vehicle_id": vid, "date": "2026-10-01", "cost_cents": "500"}).json()["id"]
    assert client.get(f"/api/v1/services/{sid}").json()["cost_cents"] == 500
    make_user(db, email="other@example.com", owner=False, chat_id=222)
    assert signed_in(db, "other@example.com").get(f"/api/v1/services/{sid}").status_code == 404
