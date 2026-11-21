import datetime as dt

import pytest
from sqlalchemy import select

from app import mcp_setup as ms
from app import models as m
from mcp.server.mcpserver.exceptions import ToolError
from tests.conftest import TODAY, make_user


def test_set_up_a_vehicle_from_scratch(db, user):
    v = ms.add_vehicle_impl(db, user, "Civic", "Honda", "Civic", 2020, current_km=84_500)
    assert v["current_km"] == 84_500
    with pytest.raises(ToolError, match="already have a vehicle"):
        ms.add_vehicle_impl(db, user, "Civic", "Honda", "Civic", 2020)

    r = ms.add_reminder_impl(db, user, "civic", "oil change", every_km=8000, every_months=12,
                             last_done_date=TODAY - dt.timedelta(days=60), last_done_km=80_000)
    assert r["service"] == "Oil change" and r["every"] == "8,000 km or 12 months" and r["note"] is None
    with pytest.raises(ToolError, match="already has a rule"):
        ms.add_reminder_impl(db, user, "Civic", "Oil change", every_km=5000)
    with pytest.raises(ToolError, match="km interval, a months interval"):
        ms.add_reminder_impl(db, user, "Civic", "Tire rotation")
    with pytest.raises(ToolError, match="Unknown service 'Flux'"):
        ms.add_reminder_impl(db, user, "Civic", "Flux", every_km=1000)

    ins = ms.add_date_impl(db, user, "insurance", TODAY + dt.timedelta(days=90), vehicle="Civic")
    assert ins["title"] == "Insurance renewal" and ins["yearly"]
    reg = ms.add_date_impl(db, user, "registration", TODAY + dt.timedelta(days=200), vehicle="Civic", warn_days=45)
    assert reg["warns_days_before"] == 45
    with pytest.raises(ToolError, match="needs a title"):
        ms.add_date_impl(db, user, "custom", TODAY)
    with pytest.raises(ToolError, match="kind must be"):
        ms.add_date_impl(db, user, "winter_install", TODAY)

    w = ms.add_winter_tire_reminders_impl(db, user, "Civic")
    assert len(w["added"]) == 2
    assert ms.add_winter_tire_reminders_impl(db, user, "Civic")["added"] == []  # no duplicates
    install = db.scalar(select(m.DateItem).where(m.DateItem.kind == "winter_install"))
    assert install.due_date == dt.date(2026, 12, 1) and install.recurs_yearly  # TODAY is 2026-11-11

    t = ms.add_tire_set_impl(db, user, "Civic", "Winters", "winter", size="215/55R17", cost=899.99)
    assert db.get(m.TireSet, t["tire_set_id"]).cost_cents == 89_999
    with pytest.raises(ToolError, match="season must be"):
        ms.add_tire_set_impl(db, user, "Civic", "x", "spring")

    p = ms.add_recurring_payment_impl(db, user, "Civic", "Insurance – Desjardins", "Insurance", 142.5, 1,
                                      dt.date(2026, 1, 15))
    assert p["amount"] == 142.5
    with pytest.raises(ToolError, match="1, 3, 6 or 12"):
        ms.add_recurring_payment_impl(db, user, "Civic", "x", "Other", 10, 2, TODAY)
    with pytest.raises(ToolError, match="between 0 and"):
        ms.add_recurring_payment_impl(db, user, "Civic", "x", "Other", float("nan"), 1, TODAY)
    with pytest.raises(ToolError, match="remind_days"):
        ms.add_recurring_payment_impl(db, user, "Civic", "x", "Other", 10, 1, TODAY, remind_days_before=10)


def test_setup_only_touches_your_vehicles(db, user):
    other = make_user(db, "b@example.com", "B", owner=False, chat_id=None)
    ms.add_vehicle_impl(db, other, "Truck", "Ford", "F150", 2015)
    for call in (lambda: ms.add_reminder_impl(db, user, "Truck", "Oil change", every_km=5000),
                 lambda: ms.add_date_impl(db, user, "insurance", TODAY, vehicle="Truck"),
                 lambda: ms.add_tire_set_impl(db, user, "Truck", "x", "winter"),
                 lambda: ms.add_recurring_payment_impl(db, user, "Truck", "x", "Other", 1, 1, TODAY),
                 lambda: ms.add_winter_tire_reminders_impl(db, user, "Truck")):
        with pytest.raises(ToolError, match="No vehicle called 'Truck'"):
            call()
    assert ms.add_vehicle_impl(db, user, "Truck", "Ram", "1500", 2019)["nickname"] == "Truck"  # names are per user
