"""Indirection so API code can trigger an evaluation without importing the evaluator at module load."""
import logging

log = logging.getLogger("evaluator")


def after_change(db, user_id: int) -> None:
    """Re-evaluate one account's alerts after it changed something. The write is already committed,
    so never raise from here. (The daily job evaluates everyone.)"""
    try:
        from app.evaluator import evaluate

        evaluate(db, user_id=user_id)
    except Exception:  # noqa: BLE001
        log.exception("alert evaluation failed after a change")
        db.rollback()
