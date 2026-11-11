import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.clock import tz
from app.db import SessionLocal
from app.evaluator import evaluate
from app.notify.factory import get_notifier
from app.notify.outbox import dispatch

log = logging.getLogger("scheduler")


def run_evaluate() -> None:
    with SessionLocal() as db:
        n = evaluate(db)
        if n:
            log.info("queued %d alert(s)", n)


def run_dispatch() -> None:
    with SessionLocal() as db:
        dispatch(db, get_notifier())


def start() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz())
    sched.add_job(run_evaluate, "cron", hour=8, minute=0, id="daily-evaluate", misfire_grace_time=3600)
    sched.add_job(run_dispatch, "interval", seconds=30, id="dispatch-outbox", max_instances=1)
    sched.start()
    return sched
