import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.notify.base import Action, Notifier
from app.notify.models import NotificationOutbox

MAX_ATTEMPTS = 5  # quick retries (the dispatcher runs every ~30 s)
MAX_TOTAL_ATTEMPTS = 60  # after the quick ones, retry with a growing delay for about a day
BACKOFF_STEP = timedelta(minutes=10)
_SECRET = re.compile(r"bot\d+:[\w-]+")


def redact(text: str) -> str:
    """Telegram puts the bot token in request URLs, which end up in exception messages."""
    return _SECRET.sub("bot<redacted>", text)


def _eligible(row: NotificationOutbox, now: datetime) -> bool:
    if row.attempts < MAX_ATTEMPTS:
        return True
    if row.attempts >= MAX_TOTAL_ATTEMPTS:
        return False
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
    return now - created >= BACKOFF_STEP * (row.attempts - MAX_ATTEMPTS + 1)


def enqueue(db: Session, source: str, dedupe_key: str, title: str, body: str,
            actions: list[Action] | None = None) -> bool:
    """Queue a message. Returns False (and queues nothing) if dedupe_key was already used."""
    if db.scalar(select(NotificationOutbox.id).where(NotificationOutbox.dedupe_key == dedupe_key)):
        return False
    db.add(NotificationOutbox(source=source, dedupe_key=dedupe_key, title=title, body=body,
                              actions_json=json.dumps([[a.label, a.callback_id] for a in actions or []])))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def dispatch(db: Session, notifier: Notifier) -> int:
    """Send pending messages, oldest first. Failures are recorded and retried on the next run."""
    now = datetime.now(timezone.utc)
    pending = [r for r in db.scalars(select(NotificationOutbox).where(
        NotificationOutbox.sent_at.is_(None), NotificationOutbox.attempts < MAX_TOTAL_ATTEMPTS)
        .order_by(NotificationOutbox.id)) if _eligible(r, now)]
    sent = 0
    for row in pending:
        actions = [Action(label, cb) for label, cb in json.loads(row.actions_json)]
        row.attempts += 1
        try:
            notifier.send(row.title, row.body, actions)
        except Exception as e:  # noqa: BLE001 - any failure means retry later
            row.last_error = redact(f"{type(e).__name__}: {e}")[:500]
        else:
            row.sent_at = datetime.now(timezone.utc)
            row.last_error = None
            sent += 1
        db.commit()
    return sent
