from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings


def tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def today_local() -> date:
    return datetime.now(tz()).date()


def as_local_date(dt: datetime) -> date:
    """SQLite returns naive datetimes; they are stored as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz()).date()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
