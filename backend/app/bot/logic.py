"""Bot behaviour as plain functions: text in, Reply out. Telegram glue lives in runner.py."""
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.bot.parser import guess_vehicle, parse_mileage
from app.clock import today_local
from app.domain.due import roll_yearly
from app.domain.status import ORDER
from app.services import evaluator_hook, odometer, records, status

BIG_JUMP_KM = 5000
RECENT_VISIT_DAYS = 7


@dataclass
class Reply:
    text: str
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (label, callback_data)


def _vehicles(db: Session) -> list[m.Vehicle]:
    return list(db.scalars(select(m.Vehicle).where(m.Vehicle.archived.is_(False)).order_by(m.Vehicle.nickname)))


def _picker(db: Session, km: int, exclude: int | None = None) -> list[tuple[str, str]]:
    return [(v.nickname, f"km:{v.id}:{km}") for v in _vehicles(db) if v.id != exclude]


def handle_text(db: Session, text: str) -> Reply:
    vehicles = _vehicles(db)
    if not vehicles:
        return Reply("No vehicles yet. Add one in the app first.")
    p = parse_mileage(text, [v.nickname for v in vehicles])
    if p.error:
        return Reply(p.error)
    if p.nickname:
        vid = next(v.id for v in vehicles if v.nickname == p.nickname)
    else:
        vid = guess_vehicle(p.km, [(v.id, odometer.current_km(db, v.id)) for v in vehicles])
    if vid is None:
        return Reply(f"Which vehicle is {p.km:,} km?", _picker(db, p.km))
    return log_km(db, vid, p.km, confirmed=False)


def log_km(db: Session, vid: int, km: int, confirmed: bool, correction: bool = False) -> Reply:
    v = db.get(m.Vehicle, vid)
    cur = odometer.current_km(db, vid)
    if cur is not None and km < cur and not correction:
        return Reply(f"{km:,} km is below {v.nickname}'s current {cur:,} km. Is that a correction?",
                     [("Yes, correct it", f"corr:{vid}:{km}"), ("Cancel", "cancel")])
    if cur is not None and km - cur > BIG_JUMP_KM and not confirmed and not correction:
        return Reply(f"That's +{km - cur:,} km since {v.nickname}'s last reading ({cur:,} km). Log it?",
                     [("Yes, log it", f"ok:{vid}:{km}"), ("Cancel", "cancel")])
    try:
        r = odometer.add_reading(db, vid, km, "telegram", is_correction=correction)
    except odometer.OdometerError as e:
        return Reply(str(e))
    evaluator_hook.after_change(db)
    delta = f" (+{km - cur:,} km)" if cur is not None and km > cur else ""
    text = f"Logged {km:,} km for {v.nickname}{delta}."
    worst = [i for i in status.vehicle_items(db, vid, today_local()) if i.status in ("overdue", "due_soon")
             and not i.informational]
    if worst:
        text += f"\nNext: {worst[0].title}, {worst[0].detail}"
    return Reply(text, [("Wrong vehicle", f"wrong:{r.id}")])


def handle_callback(db: Session, data: str) -> Reply:
    parts = data.split(":")
    kind = parts[0]
    try:
        if kind == "cancel":
            return Reply("Okay, nothing logged.")
        if kind in ("km", "ok", "corr"):
            vid, km = int(parts[1]), int(parts[2])
            return log_km(db, vid, km, confirmed=True, correction=kind == "corr")
        if kind == "wrong":
            r = db.get(m.OdometerReading, int(parts[1]))
            if not r:
                return Reply("That reading is already gone.")
            km, old = r.km, r.vehicle_id
            db.delete(r)
            db.commit()
            return Reply(f"Removed. Which vehicle is {km:,} km?", _picker(db, km, exclude=old))
        if kind == "done" and parts[1] == "rule":
            from app.api.rules import mark_rule_done
            rule = db.get(m.ReminderRule, int(parts[2]))
            if not rule:
                return Reply("That reminder no longer exists.")
            if status.rule_anchor(db, rule) and status.rule_anchor(db, rule).date == today_local():
                return Reply(f"{rule.service_type.name} is already logged as done today.")  # double tap
            rec = mark_rule_done(db, rule)
            km = f" at {rec.odometer_km:,} km" if rec.odometer_km else ""
            return Reply(f"Logged {rule.service_type.name} as done today{km}.", [("Undo", f"undo:{rec.id}")])
        if kind == "done" and parts[1] == "date":
            di = db.get(m.DateItem, int(parts[2]))
            if not di:
                return Reply("That item no longer exists.")
            if di.recurs_yearly:
                di.due_date = roll_yearly(di.due_date, today_local())
            else:
                db.delete(di)
            db.commit()
            evaluator_hook.after_change(db)
            return Reply(f"Marked '{di.title}' done.")
        if kind == "undo":
            rec = db.get(m.ServiceRecord, int(parts[1]))
            # only undo a bare "done today" entry from the bot, never an older or detailed visit
            if rec and rec.date == today_local() and rec.cost_cents == 0 and not rec.attachments and not rec.vendor:
                db.delete(rec)
                db.commit()
                evaluator_hook.after_change(db)
            return Reply("Undone.")
        if kind == "snooze":
            from app.api.rules import snooze_subject
            snooze_subject(db, f"{parts[1]}:{parts[2]}", int(parts[3]))
            return Reply(f"Snoozed for {parts[3]} days.")
        if kind == "rmove":
            rec = db.get(m.ServiceRecord, int(parts[1]))
            v = db.get(m.Vehicle, int(parts[2]))
            if not rec or not v:
                return Reply("Couldn't find that.")
            rec.vehicle_id = v.id
            db.commit()
            return Reply(f"Moved the receipt to {v.nickname}.")
    except (IndexError, ValueError):
        pass
    except Exception as e:  # noqa: BLE001 - never crash the bot on a stale button
        return Reply(f"That didn't work ({getattr(e, 'detail', e)}).")
    return Reply("I didn't understand that button.")


def handle_attachment(db: Session, filename: str, data: bytes) -> Reply:
    if records.sniff_mime(data) is None:
        return Reply("I can only file JPEG, PNG, WebP, HEIC or PDF receipts.")
    if len(data) > records.MAX_UPLOAD:
        return Reply("That file is over 20 MB.")
    today = today_local()
    recent = db.scalar(select(m.ServiceRecord).where(
        m.ServiceRecord.date >= today - timedelta(days=RECENT_VISIT_DAYS))
        .order_by(m.ServiceRecord.date.desc(), m.ServiceRecord.id.desc()))
    if recent:
        records.save_attachment(db, recent, filename, data)
        db.commit()
        v = db.get(m.Vehicle, recent.vehicle_id)
        return Reply(f"Attached to {v.nickname}'s service on {recent.date:%b} {recent.date.day}.")
    vehicles = _vehicles(db)
    if not vehicles:
        return Reply("No vehicles yet. Add one in the app first.")
    vid = max(vehicles, key=lambda v: odometer.valid_readings(db, v.id)[-1].recorded_at.timestamp()
              if odometer.valid_readings(db, v.id) else 0).id
    rec = records.log_service(db, vid, today, None, 0, None, "Receipt only (from Telegram)", [], commit=False)
    records.save_attachment(db, rec, filename, data)
    db.commit()
    v = db.get(m.Vehicle, vid)
    buttons = [(f"It's {o.nickname}", f"rmove:{rec.id}:{o.id}") for o in vehicles if o.id != vid]
    return Reply(f"No recent service, so I saved it as a receipt-only entry for {v.nickname}. "
                 "You can add details in the app.", buttons)


def cmd_due(db: Session) -> Reply:
    lines = []
    for i in sorted(status.all_items(db, today_local()), key=lambda i: ORDER[i.status]):
        if i.status in ("overdue", "due_soon") and not i.informational:
            v = db.get(m.Vehicle, i.vehicle_id) if i.vehicle_id else None
            icon = "⛔" if i.status == "overdue" else "⚠️"
            lines.append(f"{icon} {(v.nickname + ': ') if v else ''}{i.title}: {i.detail}")
    return Reply("\n".join(lines) or "Nothing due. ✅")


def cmd_vehicles(db: Session) -> Reply:
    lines = [f"{v.nickname} ({v.year} {v.make} {v.model}): "
             f"{(odometer.current_km(db, v.id) or 0):,} km" for v in _vehicles(db)]
    return Reply("\n".join(lines) or "No vehicles yet.")


HELP = ("Send your odometer reading, e.g. `84500`, `84,500 km`, `84.5k` or `civic 84500`.\n"
        "Send a photo or PDF to file a receipt.\n"
        "/due: what needs attention\n/vehicles: current mileage")


def cmd_help(db: Session) -> Reply:
    return Reply(HELP)
