import datetime as dt

from sqlalchemy import select

from app import models as m
from app.api.rules import snooze_subject
from app.domain.recurring import next_occurrence, occurrences
from app.evaluator import evaluate
from tests.conftest import make_user, signed_in

D = dt.date


# ---- pure dates ----

def test_month_end_payments_clamp_and_come_back():
    got = occurrences(D(2026, 1, 31), 1, None, D(2026, 1, 1), D(2026, 4, 30))
    assert got == [D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)]


def test_end_date_and_range_bounds():
    assert occurrences(D(2026, 1, 15), 1, D(2026, 3, 14), D(2026, 1, 1), D(2026, 12, 31)) == \
        [D(2026, 1, 15), D(2026, 2, 15)]
    assert occurrences(D(2026, 1, 15), 3, None, D(2026, 5, 1), D(2027, 1, 31)) == \
        [D(2026, 7, 15), D(2026, 10, 15), D(2027, 1, 15)]
    assert occurrences(D(2027, 1, 1), 1, None, D(2026, 1, 1), D(2026, 12, 31)) == []  # starts later


def test_skipping_ahead_from_an_old_start_misses_nothing():
    got = occurrences(D(2010, 3, 10), 6, None, D(2026, 1, 1), D(2026, 12, 31))
    assert got == [D(2026, 3, 10), D(2026, 9, 10)]


def test_next_occurrence():
    assert next_occurrence(D(2025, 3, 1), 12, None, D(2026, 11, 11)) == D(2027, 3, 1)
    assert next_occurrence(D(2026, 1, 11), 1, None, D(2026, 11, 11)) == D(2026, 11, 11)
    assert next_occurrence(D(2026, 1, 1), 1, D(2026, 6, 30), D(2026, 11, 11)) is None


# ---- API ----

def _vehicle(client, nickname="civic"):
    r = client.post("/api/v1/vehicles", json={"nickname": nickname, "make": "Honda", "model": "Civic", "year": 2020})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _cost(client, vid, **kw):
    body = {"name": "Insurance", "category": "Insurance", "amount_cents": 14200, "every_months": 1,
            "start_date": "2026-01-05"} | kw
    return client.post(f"/api/v1/vehicles/{vid}/recurring-costs", json=body)


def test_crud_and_next_date(client):
    vid = _vehicle(client)
    r = _cost(client, vid)
    assert r.status_code == 201, r.text
    cost = r.json()
    assert cost["next_date"] == "2026-12-05"
    patched = client.patch(f"/api/v1/recurring-costs/{cost['id']}", json={"amount_cents": 15000})
    assert patched.json()["amount_cents"] == 15000
    assert len(client.get(f"/api/v1/vehicles/{vid}/recurring-costs").json()) == 1
    assert client.delete(f"/api/v1/recurring-costs/{cost['id']}").status_code == 204
    assert client.get(f"/api/v1/vehicles/{vid}/recurring-costs").json() == []


def test_validation(client):
    vid = _vehicle(client)
    assert _cost(client, vid, every_months=2).status_code == 422
    assert _cost(client, vid, amount_cents=0).status_code == 422
    assert _cost(client, vid, end_date="2025-01-01").status_code == 422
    # a reminder only makes sense for yearly payments
    assert _cost(client, vid, remind_days=30).json()["remind_days"] is None
    assert _cost(client, vid, every_months=12, remind_days=30).json()["remind_days"] == 30


def test_other_peoples_costs_are_not_found(db, client):
    vid = _vehicle(client)
    cid = _cost(client, vid).json()["id"]
    make_user(db, email="other@example.com", owner=False, chat_id=222)
    other = signed_in(db, "other@example.com")
    assert other.get(f"/api/v1/vehicles/{vid}/recurring-costs").status_code == 404
    assert other.patch(f"/api/v1/recurring-costs/{cid}", json={"amount_cents": 1}).status_code == 404
    assert other.delete(f"/api/v1/recurring-costs/{cid}").status_code == 404
    assert other.post(f"/api/v1/recurring-costs/{cid}/change-amount",
                      json={"amount_cents": 1, "from_date": "2026-06-01"}).status_code == 404
    assert _cost(other, vid).status_code == 404
    assert other.get(f"/api/v1/spending?vehicle={vid}").status_code == 404
    assert other.get("/api/v1/spending").json()["total_cents"] == 0


def test_change_amount_keeps_old_payments_at_the_old_price(client):
    vid = _vehicle(client)
    cid = _cost(client, vid, amount_cents=10000).json()["id"]
    r = client.post(f"/api/v1/recurring-costs/{cid}/change-amount",
                    json={"amount_cents": 12000, "from_date": "2026-07-01"})
    assert r.status_code == 201, r.text
    rows = client.get(f"/api/v1/vehicles/{vid}/recurring-costs").json()
    assert {(c["amount_cents"], c["start_date"], c["end_date"]) for c in rows} == \
        {(10000, "2026-01-05", "2026-06-30"), (12000, "2026-07-01", None)}
    s = client.get("/api/v1/spending?from=2026-01-01&to=2026-12-31").json()
    # Jan-Jun at 100, Jul 1 + Aug-Nov at 120 (the new row starts Jul 1, then the 1st of each month)
    assert s["total_cents"] == 6 * 10000 + 5 * 12000
    assert s["scheduled_cents"] == 12000  # Dec 1
    assert client.post(f"/api/v1/recurring-costs/{cid}/change-amount",
                       json={"amount_cents": 1, "from_date": "2026-01-01"}).status_code == 422


def test_spending_months_categories_and_filters(client):
    vid = _vehicle(client)
    _cost(client, vid, start_date="2026-09-20")
    _cost(client, vid, name="SAAQ", category="Registration", amount_cents=30000, every_months=12,
          start_date="2026-10-01")
    s = client.get("/api/v1/spending?from=2026-08-01&to=2026-12-31").json()
    assert [mo["month"] for mo in s["by_month"]] == ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
    assert [mo["total_cents"] for mo in s["by_month"]] == [0, 14200, 44200, 0, 0]  # Nov 20 hasn't happened
    assert s["by_category"] == {"Registration": 30000, "Insurance": 28400}
    assert s["scheduled_cents"] == 2 * 14200
    assert s["categories"] == ["Insurance", "Registration"]
    only = client.get("/api/v1/spending?from=2026-08-01&to=2026-12-31&category=Registration").json()
    assert only["total_cents"] == 30000 and only["categories"] == ["Insurance", "Registration"]
    assert all(e["category"] == "Registration" for e in only["entries"])
    assert client.get("/api/v1/spending?from=2026-12-01&to=2026-01-01").status_code == 422


def test_spending_includes_services_and_defaults_to_this_year(demo_client):
    s = demo_client.get("/api/v1/spending").json()
    assert len(s["by_month"]) == 12 and s["by_month"][0]["month"] == "2026-01"
    assert s["total_cents"] > 0
    assert any(e["source"] == "service" for e in s["entries"])


def test_yearly_report_counts_recurring_payments(client):
    vid = _vehicle(client)
    _cost(client, vid, start_date="2025-12-05")
    rows = {y["year"]: y for y in client.get("/api/v1/reports").json()["years"]}
    assert rows[2025]["by_category"]["Insurance"] == 14200
    assert rows[2026]["by_category"]["Insurance"] == 11 * 14200  # Dec 5, 2026 hasn't happened yet


def test_spending_csv_guards_formulas(client):
    vid = _vehicle(client)
    _cost(client, vid, name="=HYPERLINK(1)")
    text = client.get("/api/v1/export/spending.csv?from=2026-01-01&to=2026-12-31").text
    assert "'=HYPERLINK(1)" in text and "scheduled" in text


# ---- yearly renewal alerts ----

def _add(db, user, **kw):
    v = m.Vehicle(nickname="civic", make="Honda", model="Civic", year=2020, user_id=user.id)
    db.add(v)
    db.flush()
    fields = {"every_months": 12, "start_date": D(2025, 12, 1), "remind_days": 30} | kw
    rc = m.RecurringCost(vehicle_id=v.id, name="Insurance", category="Insurance", amount_cents=171200, **fields)
    db.add(rc)
    db.commit()
    return rc


def _outbox(db):
    return db.scalars(select(m.NotificationOutbox)).all()


def test_yearly_renewal_alerts_once_per_year(db, user):
    _add(db, user)  # renews Dec 1, 2026: 20 days away, inside the 30-day window
    assert evaluate(db) == 1
    [out] = _outbox(db)
    assert out.title == "civic: Insurance renews soon"
    assert "$1,712.00" in out.body
    assert "done:" not in out.actions_json and "snooze:cost:" in out.actions_json
    assert evaluate(db) == 0
    assert evaluate(db, today=D(2027, 11, 15)) == 1  # next year's renewal is a new cycle


def test_no_alert_outside_the_window_or_for_monthly(db, user):
    _add(db, user, start_date=D(2026, 3, 1))  # renews Mar 1: too far away
    assert evaluate(db) == 0
    other = make_user(db, email="b@example.com", owner=False, chat_id=333)
    v = m.Vehicle(nickname="other", make="X", model="Y", year=2020, user_id=other.id)
    db.add(v)
    db.flush()
    db.add(m.RecurringCost(vehicle_id=v.id, name="Lease", category="Financing", amount_cents=100,
                           every_months=1, start_date=D(2026, 1, 12), remind_days=3))
    db.commit()
    assert evaluate(db) == 0


def test_renewal_can_be_snoozed(db, user):
    rc = _add(db, user)
    snooze_subject(db, user, f"cost:{rc.id}", 7)
    assert evaluate(db) == 0


def test_archiving_a_vehicle_ends_its_payments(client):
    vid = _vehicle(client)
    _cost(client, vid)
    assert client.patch(f"/api/v1/vehicles/{vid}", json={"archived": True}).status_code == 200
    [c] = client.get(f"/api/v1/vehicles/{vid}/recurring-costs").json()
    assert c["end_date"] == "2026-11-11" and c["next_date"] is None
    later = client.get("/api/v1/spending?from=2027-01-01&to=2027-12-31").json()
    assert later["total_cents"] == 0 and later["scheduled_cents"] == 0
