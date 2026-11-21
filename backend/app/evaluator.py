"""Decides when to alert. Writes to the outbox only; sending happens in notify.dispatch."""
import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models as m
from app.clock import now_utc, today_local
from app.domain.due import DUE_SOON, OVERDUE
from app.notify.base import Action
from app.notify.outbox import enqueue
from app.services.status import StatusItem, all_items

log = logging.getLogger("evaluator")
SEVERITY = {DUE_SOON: 1, OVERDUE: 2}


def _aware(dt: datetime) -> datetime:
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _message(db: Session, item: StatusItem, realert: bool) -> tuple[str, str, list[Action]]:
    v = db.get(m.Vehicle, item.vehicle_id) if item.vehicle_id else None
    prefix = f"{v.nickname}: " if v else ""
    verb = "is overdue" if item.status == OVERDUE else "is due soon"
    title = f"{prefix}{item.title} {'still ' if realert else ''}{verb}"
    sid = item.subject
    snooze = Action("Snooze 7 d", f"snooze:{sid}:7")
    if item.kind == "cost":  # paid automatically: nothing to mark done
        return f"{prefix}{item.title} renews soon", item.detail, [snooze]
    return title, item.detail, [Action("Done today" if item.kind == "rule" else "Done", f"done:{sid}"), snooze]


def _recipient(item: StatusItem) -> str:
    """Alerts are addressed to the owning account; the chat is looked up when sending (resolve_recipient)."""
    return f"user:{item.owner_id}"


def resolve_recipient(db: Session, recipient: str | None) -> str | None:
    """'user:12' -> where that account gets alerts right now, e.g. 'discord:4567' or 'telegram:111',
    or None (held until they link a chat app)."""
    if not recipient or not recipient.startswith("user:"):
        return None
    user = db.get(m.User, int(recipient.split(":", 1)[1]))
    return alert_address(user) if user else None


def linked_channels(user: m.User) -> dict[str, int]:
    """The user's linked chat apps that this server can currently reach, in preference order."""
    from app.notify.factory import available_channels

    linked = {"telegram": user.telegram_chat_id, "discord": user.discord_user_id}
    # with no bot configured at all (log mode), keep every link: alerts only go to the log anyway
    reachable = available_channels() or list(linked)
    return {ch: linked[ch] for ch in reachable if linked.get(ch)}


def alert_address(user: m.User) -> str | None:
    linked = linked_channels(user)
    if not linked:
        return None
    channel = user.alert_channel if user.alert_channel in linked else next(iter(linked))
    return f"{channel}:{linked[channel]}"


def forget_alerts(db: Session, subject: str) -> None:
    """Call when deleting a rule/date/payment. SQLite can hand its id to the next new one, which would otherwise
    inherit this one's alert state and used dedupe keys, and never alert."""
    from app.notify.models import NotificationOutbox

    db.execute(delete(m.AlertState).where(m.AlertState.subject == subject))
    db.execute(delete(NotificationOutbox).where(NotificationOutbox.dedupe_key.like(f"{subject}|%")))


def evaluate(db: Session, today=None, now: datetime | None = None, user_id: int | None = None) -> int:
    """Returns how many alerts were queued. Everyone's items, or one account's when user_id is given."""
    today = today or today_local()
    now = now or now_utc()
    queued = 0
    try:
        items = all_items(db, today, user_id=user_id)
    except Exception:  # noqa: BLE001 - e.g. one bad rule; log it rather than stop all alerting
        log.exception("could not compute status items")
        return 0
    for item in items:
        # informational items never alert; ownerless (pre-accounts) data is evaluated once the owner claims it
        if item.informational or item.owner_id is None:
            continue
        st = db.scalar(select(m.AlertState).where(m.AlertState.subject == item.subject,
                                                  m.AlertState.cycle_key == item.cycle_key))
        sev = SEVERITY.get(item.status, 0)
        if st is None:
            if not sev:
                continue
            st = m.AlertState(subject=item.subject, cycle_key=item.cycle_key, status="ok", changed_at=now)
            db.add(st)
        prev_sev = SEVERITY.get(st.status, 0)
        snoozed = st.snoozed_until is not None and _aware(st.snoozed_until) > now
        if item.status != st.status:
            st.status, st.changed_at = item.status, now
            if sev > prev_sev and not snoozed:
                t, b, a = _message(db, item, False)
                queued += enqueue(db, "vehicle-tracker", f"{item.subject}|{item.cycle_key}|{item.status}", t, b, a,
                                  recipient=_recipient(item))
        elif sev and st.snoozed_until is not None and not snoozed and not st.realerted:
            st.realerted = True
            t, b, a = _message(db, item, True)
            queued += enqueue(db, "vehicle-tracker",
                              f"{item.subject}|{item.cycle_key}|realert|{st.snoozed_until.isoformat()}", t, b, a,
                              recipient=_recipient(item))
    db.commit()
    return queued
