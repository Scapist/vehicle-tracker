"""Decides when to alert. Writes to the outbox only; sending happens in notify.dispatch."""
import logging
from datetime import datetime

from sqlalchemy import select
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
    return title, item.detail, [Action("Done today" if item.kind == "rule" else "Done", f"done:{sid}"),
                                Action("Snooze 7 d", f"snooze:{sid}:7")]


def evaluate(db: Session, today=None, now: datetime | None = None) -> int:
    """Returns how many alerts were queued."""
    today = today or today_local()
    now = now or now_utc()
    queued = 0
    try:
        items = all_items(db, today)
    except Exception:  # noqa: BLE001 - e.g. one bad rule; log it rather than stop all alerting
        log.exception("could not compute status items")
        return 0
    for item in items:
        if item.informational:
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
                queued += enqueue(db, "vehicle-tracker", f"{item.subject}|{item.cycle_key}|{item.status}", t, b, a)
        elif sev and st.snoozed_until is not None and not snoozed and not st.realerted:
            st.realerted = True
            t, b, a = _message(db, item, True)
            queued += enqueue(db, "vehicle-tracker",
                              f"{item.subject}|{item.cycle_key}|realert|{st.snoozed_until.isoformat()}", t, b, a)
    db.commit()
    return queued
