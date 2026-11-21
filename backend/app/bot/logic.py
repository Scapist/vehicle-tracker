"""Bot behaviour as plain functions: text in, Reply out. The same for every chat app; the Telegram glue lives
in runner.py and the Discord glue in discord_runner.py.

Every function acts for one account (`user`, found from the chat) and only ever touches that
account's vehicles. Button data carries raw ids, so each callback re-checks ownership before acting."""
import time
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.api.deps import find_owned_vehicle
from app.bot.parser import guess_vehicle, parse_mileage
from app.clock import today_local
from app.domain.due import roll_yearly
from app.domain.status import ORDER
from app.services import evaluator_hook, odometer, records, status

BIG_JUMP_KM = 5000
RECENT_VISIT_DAYS = 7
LINK_ATTEMPTS = 5
LINK_WINDOW = 10 * 60
_link_attempts: dict[str, list[float]] = {}
LABELS = {"telegram": "Telegram", "discord": "Discord"}


def link_allowed(chat_id: int | str, now: float | None = None) -> bool:
    """At most LINK_ATTEMPTS link tries per chat per window, so codes can't be guessed."""
    now = now or time.time()
    key = str(chat_id)
    recent = [t for t in _link_attempts.get(key, []) if now - t < LINK_WINDOW]
    recent.append(now)
    _link_attempts[key] = recent
    return len(recent) <= LINK_ATTEMPTS


@dataclass
class Reply:
    text: str
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (label, callback_data)


GONE = Reply("That's no longer available.")


def _vehicles(db: Session, user: m.User) -> list[m.Vehicle]:
    return list(db.scalars(select(m.Vehicle).where(m.Vehicle.user_id == user.id, m.Vehicle.archived.is_(False))
                           .order_by(m.Vehicle.nickname)))


_vehicle = find_owned_vehicle


def _picker(db: Session, user: m.User, km: int, exclude: int | None = None) -> list[tuple[str, str]]:
    return [(v.nickname, f"km:{v.id}:{km}") for v in _vehicles(db, user) if v.id != exclude]


def handle_text(db: Session, user: m.User, text: str, channel: str = "telegram") -> Reply:
    vehicles = _vehicles(db, user)
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
        return Reply(f"Which vehicle is {p.km:,} km?", _picker(db, user, p.km))
    return log_km(db, user, vid, p.km, confirmed=False, source=channel)


def log_km(db: Session, user: m.User, vid: int, km: int, confirmed: bool, correction: bool = False,
           source: str = "telegram") -> Reply:
    v = _vehicle(db, user, vid)
    if not v:
        return GONE
    cur = odometer.current_km(db, vid)
    if cur is not None and km < cur and not correction:
        return Reply(f"{km:,} km is below {v.nickname}'s current {cur:,} km. Is that a correction?",
                     [("Yes, correct it", f"corr:{vid}:{km}"), ("Cancel", "cancel")])
    if cur is not None and km - cur > BIG_JUMP_KM and not confirmed and not correction:
        return Reply(f"That's +{km - cur:,} km since {v.nickname}'s last reading ({cur:,} km). Log it?",
                     [("Yes, log it", f"ok:{vid}:{km}"), ("Cancel", "cancel")])
    try:
        r = odometer.add_reading(db, vid, km, source, is_correction=correction)
    except odometer.OdometerError as e:
        return Reply(str(e))
    evaluator_hook.after_change(db, user.id)
    delta = f" (+{km - cur:,} km)" if cur is not None and km > cur else ""
    text = f"Logged {km:,} km for {v.nickname}{delta}."
    worst = [i for i in status.vehicle_items(db, vid, today_local()) if i.status in ("overdue", "due_soon")
             and not i.informational]
    if worst:
        text += f"\nNext: {worst[0].title}, {worst[0].detail}"
    if correction:  # deleting a correction couldn't restore the readings it replaced, so no undo button
        return Reply(text)
    return Reply(text, [("Wrong vehicle", f"wrong:{r.id}")])


def handle_callback(db: Session, user: m.User, data: str, channel: str = "telegram") -> Reply:
    parts = data.split(":")
    kind = parts[0]
    try:
        if kind == "cancel":
            return Reply("Okay, nothing logged.")
        if kind in ("km", "ok", "corr"):
            vid, km = int(parts[1]), int(parts[2])
            # a vehicle picked from the "which vehicle?" list still gets the big-jump check
            return log_km(db, user, vid, km, confirmed=kind == "ok", correction=kind == "corr", source=channel)
        if kind == "wrong":
            r = db.get(m.OdometerReading, int(parts[1]))
            if not r or not _vehicle(db, user, r.vehicle_id):
                return Reply("That reading is already gone.")
            if r.is_correction:
                return Reply("A correction can't be moved. Log the right reading in the app instead.")
            km, old = r.km, r.vehicle_id
            db.delete(r)
            db.commit()
            return Reply(f"Removed. Which vehicle is {km:,} km?", _picker(db, user, km, exclude=old))
        if kind == "done" and parts[1] == "rule":
            from app.api.rules import mark_rule_done
            rule = db.get(m.ReminderRule, int(parts[2]))
            if not rule or not _vehicle(db, user, rule.vehicle_id):
                return Reply("That reminder no longer exists.")
            anchor = status.rule_anchor(db, rule)
            if anchor and anchor.date == today_local():
                return Reply(f"{rule.service_type.name} is already logged as done today.")  # double tap
            rec = mark_rule_done(db, rule)
            km = f" at {rec.odometer_km:,} km" if rec.odometer_km else ""
            return Reply(f"Logged {rule.service_type.name} as done today{km}.", [("Undo", f"undo:{rec.id}")])
        if kind == "done" and parts[1] == "date":
            di = db.get(m.DateItem, int(parts[2]))
            if not di or di.user_id != user.id:
                return Reply("That item no longer exists.")
            title = di.title
            if di.recurs_yearly:
                di.due_date = roll_yearly(di.due_date, today_local())
            else:
                db.delete(di)
            db.commit()
            evaluator_hook.after_change(db, user.id)
            return Reply(f"Marked '{title}' done.")
        if kind == "undo":
            rec = db.get(m.ServiceRecord, int(parts[1]))
            # only undo a bare "done today" entry from the bot, never an older or detailed visit
            if (rec and _vehicle(db, user, rec.vehicle_id) and rec.date == today_local() and rec.cost_cents == 0
                    and not rec.attachments and not rec.vendor):
                db.delete(rec)
                db.commit()
                evaluator_hook.after_change(db, user.id)
            return Reply("Undone.")
        if kind == "snooze":
            from app.api.rules import snooze_subject
            snooze_subject(db, user, f"{parts[1]}:{parts[2]}", int(parts[3]))  # 404s if not this user's
            return Reply(f"Snoozed for {parts[3]} days.")
        if kind == "nudge" and parts[1] == "off":
            v = _vehicle(db, user, int(parts[2]))
            if not v:
                return Reply("Couldn't find that vehicle.")
            v.nudge_days = 0
            db.commit()
            return Reply(f"Okay, I won't ask about {v.nickname}'s odometer any more. "
                         "You can turn it back on in the app (vehicle → Odometer).")
        if kind == "rmove":
            rec = db.get(m.ServiceRecord, int(parts[1]))
            v = _vehicle(db, user, int(parts[2]))
            if not rec or not v or not _vehicle(db, user, rec.vehicle_id):
                return Reply("Couldn't find that.")
            rec.vehicle_id = v.id
            db.commit()
            return Reply(f"Moved the receipt to {v.nickname}.")
    except (IndexError, ValueError):
        pass
    except Exception as e:  # noqa: BLE001 - never crash the bot on a stale or foreign button
        return Reply(f"That didn't work ({getattr(e, 'detail', e)}).")
    return Reply("I didn't understand that button.")


def handle_attachment(db: Session, user: m.User, filename: str, data: bytes, channel: str = "telegram") -> Reply:
    if records.sniff_mime(data) is None:
        return Reply("I can only file JPEG, PNG, WebP, HEIC or PDF receipts.")
    if len(data) > records.MAX_UPLOAD:
        return Reply("That file is over 20 MB.")
    vehicles = _vehicles(db, user)
    if not vehicles:
        return Reply("No vehicles yet. Add one in the app first.")
    today = today_local()
    recent = db.scalar(select(m.ServiceRecord).where(
        m.ServiceRecord.vehicle_id.in_([v.id for v in vehicles]),
        m.ServiceRecord.date >= today - timedelta(days=RECENT_VISIT_DAYS))
        .order_by(m.ServiceRecord.date.desc(), m.ServiceRecord.id.desc()))
    if recent:
        records.save_attachment(db, recent, filename, data)
        db.commit()
        v = db.get(m.Vehicle, recent.vehicle_id)
        return Reply(f"Attached to {v.nickname}'s service on {recent.date:%b} {recent.date.day}.")
    vid = max(vehicles, key=lambda v: odometer.valid_readings(db, v.id)[-1].recorded_at.timestamp()
              if odometer.valid_readings(db, v.id) else 0).id
    rec = records.log_service(db, vid, today, None, 0, None, f"Receipt only (from {LABELS.get(channel, channel)})", [], commit=False)
    records.save_attachment(db, rec, filename, data)
    db.commit()
    v = db.get(m.Vehicle, vid)
    buttons = [(f"It's {o.nickname}", f"rmove:{rec.id}:{o.id}") for o in vehicles if o.id != vid]
    return Reply(f"No recent service, so I saved it as a receipt-only entry for {v.nickname}. "
                 "You can add details in the app.", buttons)


def cmd_due(db: Session, user: m.User) -> Reply:
    lines = []
    for i in sorted(status.all_items(db, today_local(), user_id=user.id), key=lambda i: ORDER[i.status]):
        if i.status in ("overdue", "due_soon") and not i.informational:
            v = db.get(m.Vehicle, i.vehicle_id) if i.vehicle_id else None
            icon = "⛔" if i.status == "overdue" else "⚠️"
            lines.append(f"{icon} {(v.nickname + ': ') if v else ''}{i.title}: {i.detail}")
    return Reply("\n".join(lines) or "Nothing due. ✅")


def cmd_vehicles(db: Session, user: m.User) -> Reply:
    lines = [f"{v.nickname} ({v.year} {v.make} {v.model}): "
             f"{(odometer.current_km(db, v.id) or 0):,} km" for v in _vehicles(db, user)]
    return Reply("\n".join(lines) or "No vehicles yet.")


HELP = ("Send your odometer reading, e.g. `84500`, `84,500 km`, `84.5k` or `civic 84500`.\n"
        "Send a photo or PDF to file a receipt.\n"
        "/due: what needs attention\n/vehicles: current mileage")

NOT_LINKED = ("This chat isn't linked to an account yet. In the app, open Settings → Chat apps → "
              "Connect, then send the link command it shows you here.")


def cmd_help(db: Session, user: m.User) -> Reply:
    return Reply(HELP)


def cmd_link(db: Session, chat_id: int, code: str, channel: str = "telegram") -> Reply:
    from app.auth import consume_link_code

    user = consume_link_code(db, code, chat_id, channel)
    if not user:
        return Reply("That code is wrong or expired. Get a new one in the app under Settings → Chat apps.")
    return Reply(f"Linked to {user.name}'s account. You can log your km here.\n\n{help_text(channel)}")


def help_text(channel: str = "telegram") -> str:
    if channel == "discord":
        return HELP.replace("`", "").replace("/due", "!due").replace("/vehicles", "!vehicles")
    return HELP


def user_for(db: Session, channel: str, address: int) -> m.User | None:
    column = m.User.discord_user_id if channel == "discord" else m.User.telegram_chat_id
    return db.scalar(select(m.User).where(column == address))


def user_for_chat(db: Session, chat_id: int) -> m.User | None:
    return user_for(db, "telegram", chat_id)
