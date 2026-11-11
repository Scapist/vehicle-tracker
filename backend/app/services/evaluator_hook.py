"""Indirection so API code can trigger an evaluation without importing the evaluator at module load."""
import logging

log = logging.getLogger("evaluator")


def after_change(db) -> None:
    """Re-evaluate alerts after a write. The write is already committed, so never raise from here."""
    try:
        from app.evaluator import evaluate

        evaluate(db)
    except Exception:  # noqa: BLE001
        log.exception("alert evaluation failed after a change")
        db.rollback()
