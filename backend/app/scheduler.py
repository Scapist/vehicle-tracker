import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.clock import tz
from app.db import SessionLocal
from app.evaluator import evaluate, resolve_recipient
from app.nudge import queue_nudges
from app.notify.base import TelegramNotifier
from app.notify.factory import get_notifier
from app.notify.outbox import dispatch

log = logging.getLogger("scheduler")


def run_evaluate() -> None:
    with SessionLocal() as db:
        n = evaluate(db)
        if n:
            log.info("queued %d alert(s)", n)


def run_nudges() -> None:
    with SessionLocal() as db:
        n = queue_nudges(db)
        if n:
            log.info("asked for the odometer on %d vehicle(s)", n)


def run_dispatch() -> None:
    with SessionLocal() as db:
        notifier = get_notifier()
        if isinstance(notifier, TelegramNotifier):
            dispatch(db, notifier, resolve=lambda r: resolve_recipient(db, r))
        else:
            dispatch(db, notifier)  # log mode: write everything to the log


def start() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz())
    sched.add_job(run_evaluate, "cron", hour=8, minute=0, id="daily-evaluate", misfire_grace_time=3600)
    # evening: most cars are parked by then, so the odometer is easy to check
    sched.add_job(run_nudges, "cron", hour=18, minute=0, id="daily-nudge", misfire_grace_time=3600)
    sched.add_job(run_dispatch, "interval", seconds=30, id="dispatch-outbox", max_instances=1)
    sched.start()
    return sched
