"""MCP tools for setting things up: vehicles, reminders, dates (insurance, registration...), winter-tire reminders,
tire sets and recurring payments. Like the rest of the MCP server they only add, never edit or delete.

Each `*_impl` calls the app's own route function (the same code the web app's forms hit), so validation, ownership
checks and alert re-evaluation are identical; HTTP errors become ToolErrors the assistant can read and act on.
Registered on `mcp` when app.mcp_server imports this module."""
from contextlib import contextmanager
from datetime import date

from fastapi import HTTPException
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError
from sqlalchemy import select

from app import models as m
from app import schemas as s
from app.api.deps import visible_service_types
from app.clock import today_local
from app.mcp_server import _session, _user, find_vehicle, mcp
from app.services import odometer

DATE_KINDS = {"registration": "Registration renewal", "insurance": "Insurance renewal", "custom": None}
SEASONS = ("winter", "summer", "all_season")
FREQUENCIES = (1, 3, 6, 12)


@contextmanager
def _as_tool_errors():
    try:
        yield
    except HTTPException as e:
        raise ToolError(str(e.detail))
    except ValidationError as e:
        raise ToolError("; ".join(f"{'.'.join(map(str, x['loc'])) or 'value'}: {x['msg']}" for x in e.errors()))


def _cents(dollars: float | None, what: str) -> int | None:
    if dollars is None:
        return None
    if not 0 <= dollars <= 1_000_000:  # NaN fails too
        raise ToolError(f"{what} must be between 0 and 1,000,000 dollars.")
    return round(dollars * 100)


def _service_type(db, user: m.User, name: str) -> m.ServiceType:
    types = {t.name.lower(): t for t in db.scalars(select(m.ServiceType).where(visible_service_types(user)))}
    t = types.get(name.strip().lower())
    if not t:
        raise ToolError(f"Unknown service {name!r}. Use one of: {', '.join(sorted(x.name for x in types.values()))}. "
                        "The user can add their own services in the app (Settings → Your services).")
    return t


def add_vehicle_impl(db, user: m.User, nickname: str, make: str, model: str, year: int, vin: str | None = None,
                     current_km: int | None = None) -> dict:
    from app.api.vehicles import create_vehicle

    if current_km is not None and not 0 <= current_km <= 2_000_000:
        raise ToolError("That isn't a plausible odometer reading.")
    with _as_tool_errors():
        out = create_vehicle(s.VehicleIn(nickname=nickname.strip(), make=make.strip(), model=model.strip(),
                                         year=year, vin=vin or None), user=user, db=db)
    if current_km is not None:
        odometer.add_reading(db, out.id, current_km, "mcp")
    return {"vehicle_id": out.id, "nickname": out.nickname, "current_km": current_km,
            "next": "Add reminders (add_reminder), dates such as insurance and registration (add_date), and "
                    "winter-tire reminders (add_winter_tire_reminders) if the user changes tires."}


def add_reminder_impl(db, user: m.User, vehicle: str, service: str, every_km: int | None = None,
                      every_months: int | None = None, warn_km: int = 1000, warn_days: int = 30,
                      last_done_date: date | None = None, last_done_km: int | None = None) -> dict:
    from app.api.rules import create_rule

    v = find_vehicle(db, user, vehicle)
    t = _service_type(db, user, service)
    if last_done_date and last_done_date > today_local():
        raise ToolError("last_done_date can't be in the future.")
    with _as_tool_errors():
        rule = create_rule(v.id, s.RuleIn(service_type_id=t.id, interval_km=every_km, interval_months=every_months,
                                          soon_km=warn_km, soon_days=warn_days, baseline_date=last_done_date,
                                          baseline_km=last_done_km), user=user, db=db)
    every = " or ".join(x for x in (f"{every_km:,} km" if every_km else "", f"{every_months} months"
                                    if every_months else "") if x)
    return {"reminder_id": rule.id, "vehicle": v.nickname, "service": t.name, "every": every,
            "note": None if (last_done_date or last_done_km) else
            "With no 'last done' date or km and no logged service, this shows as Unknown until one is logged."}


def add_date_impl(db, user: m.User, kind: str, due_date: date, vehicle: str | None = None, title: str | None = None,
                  yearly: bool = True, warn_days: int = 30) -> dict:
    from app.api.rules import create_date_item

    if kind not in DATE_KINDS:
        raise ToolError("kind must be registration, insurance or custom (use add_winter_tire_reminders for tires).")
    title = (title or "").strip() or DATE_KINDS[kind]
    if not title:
        raise ToolError("A custom date needs a title, e.g. 'Safety inspection' or 'Emissions test'.")
    if not 0 <= warn_days <= 365:
        raise ToolError("warn_days must be between 0 and 365.")
    vid = find_vehicle(db, user, vehicle).id if vehicle else None
    with _as_tool_errors():
        di = create_date_item(s.DateItemIn(vehicle_id=vid, kind=kind, title=title[:120], due_date=due_date,
                                           recurs_yearly=yearly, soon_days=warn_days), user=user, db=db)
    return {"date_id": di.id, "title": di.title, "due_date": di.due_date.isoformat(), "yearly": di.recurs_yearly,
            "warns_days_before": di.soon_days}


def add_winter_tire_reminders_impl(db, user: m.User, vehicle: str) -> dict:
    """The same two dates as the app's 'Add winter-tire reminders' button (Quebec rules: Dec 1 to Mar 15)."""
    from app.api.rules import create_date_item

    v = find_vehicle(db, user, vehicle)
    existing = set(db.scalars(select(m.DateItem.kind).where(m.DateItem.vehicle_id == v.id,
                                                            m.DateItem.kind.in_(("winter_install", "winter_remove")))))
    today = today_local()
    dec = today.year if date(today.year, 12, 1) >= today else today.year + 1
    added = []
    if "winter_install" not in existing:
        create_date_item(s.DateItemIn(vehicle_id=v.id, kind="winter_install", title="Install winter tires by Dec 1",
                                      due_date=date(dec, 12, 1), recurs_yearly=True, soon_days=30), user=user, db=db)
        added.append("Install winter tires by Dec 1")
    if "winter_remove" not in existing:
        create_date_item(s.DateItemIn(vehicle_id=v.id, kind="winter_remove",
                                      title="Winter tires can come off after Mar 15", due_date=date(dec + 1, 3, 15),
                                      recurs_yearly=True, soon_days=14, informational=True), user=user, db=db)
        added.append("Winter tires can come off after Mar 15")
    return {"vehicle": v.nickname, "added": added, "already_there": sorted(existing)}


def add_tire_set_impl(db, user: m.User, vehicle: str, label: str, season: str, size: str | None = None,
                      brand_model: str | None = None, purchase_date: date | None = None, cost: float | None = None,
                      storage_location: str | None = None) -> dict:
    from app.api.tires import create_tire_set

    if season not in SEASONS:
        raise ToolError(f"season must be one of: {', '.join(SEASONS)}.")
    v = find_vehicle(db, user, vehicle)
    with _as_tool_errors():
        ts = create_tire_set(s.TireSetIn(vehicle_id=v.id, label=label.strip()[:80], season=season, size=size,
                                         brand_model=brand_model, purchase_date=purchase_date,
                                         cost_cents=_cents(cost, "cost"), storage_location=storage_location),
                             user=user, db=db)
    return {"tire_set_id": ts.id, "vehicle": v.nickname, "label": ts.label, "season": ts.season,
            "note": "Mark it as mounted in the app (Tires) when it goes on the car."}


def add_recurring_payment_impl(db, user: m.User, vehicle: str, name: str, category: str, amount: float,
                               every_months: int, first_payment: date, last_payment: date | None = None,
                               remind_days_before: int | None = None) -> dict:
    from app.api.costs import create_cost

    if every_months not in FREQUENCIES:
        raise ToolError("every_months must be 1, 3, 6 or 12.")
    if remind_days_before is not None and every_months != 12:
        raise ToolError("remind_days_before only works for yearly payments (every_months=12); monthly debits never "
                        "alert. For a monthly-paid policy, add its yearly renewal with add_date(kind='insurance').")
    cents = _cents(amount, "amount")
    if not cents:
        raise ToolError("amount must be more than 0.")
    v = find_vehicle(db, user, vehicle)
    with _as_tool_errors():
        rc = create_cost(v.id, s.RecurringCostIn(name=name.strip(), category=category.strip(), amount_cents=cents,
                                                 every_months=every_months, start_date=first_payment,
                                                 end_date=last_payment, remind_days=remind_days_before),
                         user=user, db=db)
    return {"payment_id": rc.id, "vehicle": v.nickname, "name": rc.name, "amount": cents / 100,
            "every_months": every_months, "first_payment": first_payment.isoformat()}


# ---------- MCP wrappers ----------

@mcp.tool()
def add_vehicle(ctx: Context, nickname: str, make: str, model: str, year: int, vin: str | None = None,
                current_km: int | None = None) -> dict:
    """Add a vehicle. nickname is how the user refers to it (unique per user, e.g. 'Civic'). current_km: today's
    odometer reading, if known (km reminders need at least one reading)."""
    with _session() as db:
        return add_vehicle_impl(db, _user(ctx, db), nickname, make, model, year, vin, current_km)


@mcp.tool()
def add_reminder(ctx: Context, vehicle: str, service: str, every_km: int | None = None,
                 every_months: int | None = None, warn_km: int = 1000, warn_days: int = 30,
                 last_done_date: date | None = None, last_done_km: int | None = None) -> dict:
    """Add a maintenance reminder, e.g. oil change every 8,000 km or 12 months (whichever comes first). service:
    a name from list_service_types. Give every_km, every_months or both. warn_km / warn_days: how early it turns
    'due soon'. last_done_date / last_done_km: when it was last done, if the user knows (otherwise it shows as
    Unknown until a service is logged). One reminder per service per vehicle."""
    with _session() as db:
        return add_reminder_impl(db, _user(ctx, db), vehicle, service, every_km, every_months, warn_km, warn_days,
                                 last_done_date, last_done_km)


@mcp.tool()
def add_date(ctx: Context, kind: str, due_date: date, vehicle: str | None = None, title: str | None = None,
             yearly: bool = True, warn_days: int = 30) -> dict:
    """Add a date to be reminded about. kind: 'insurance' (renewal), 'registration' (renewal, e.g. SAAQ) or
    'custom' (needs a title, e.g. 'Safety inspection'). due_date: the next due date. yearly: repeats every year
    after it's marked done. warn_days: how many days ahead it turns 'due soon' and alerts."""
    with _session() as db:
        return add_date_impl(db, _user(ctx, db), kind, due_date, vehicle, title, yearly, warn_days)


@mcp.tool()
def add_winter_tire_reminders(ctx: Context, vehicle: str) -> dict:
    """Add the two yearly winter-tire dates for a vehicle: 'Install winter tires by Dec 1' (alerts 30 days ahead)
    and 'Winter tires can come off after Mar 15' (informational). Skips any that already exist."""
    with _session() as db:
        return add_winter_tire_reminders_impl(db, _user(ctx, db), vehicle)


@mcp.tool()
def add_tire_set(ctx: Context, vehicle: str, label: str, season: str, size: str | None = None,
                 brand_model: str | None = None, purchase_date: date | None = None, cost: float | None = None,
                 storage_location: str | None = None) -> dict:
    """Add a set of tires the user owns. season: winter, summer or all_season. size like '215/55R17'. cost in
    dollars (counts toward spending on purchase_date)."""
    with _session() as db:
        return add_tire_set_impl(db, _user(ctx, db), vehicle, label, season, size, brand_model, purchase_date, cost,
                                 storage_location)


@mcp.tool()
def add_recurring_payment(ctx: Context, vehicle: str, name: str, category: str, amount: float, every_months: int,
                          first_payment: date, last_payment: date | None = None,
                          remind_days_before: int | None = None) -> dict:
    """Add a payment taken automatically, e.g. monthly insurance or financing. category: Insurance, Registration,
    Financing, Parking or Other (or another short label). amount in dollars per payment. every_months: 1, 3, 6 or
    12. first_payment sets the day of the month. Past payments count as spent automatically.
    remind_days_before: only for yearly payments, an alert that many days before each renewal."""
    with _session() as db:
        return add_recurring_payment_impl(db, _user(ctx, db), vehicle, name, category, amount, every_months,
                                          first_payment, last_payment, remind_days_before)
