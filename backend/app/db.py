from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None, foreign_keys: bool = True):
    """foreign_keys=False is only for migrations: SQLite table rebuilds (drop + rename) would otherwise
    cascade-delete every child row."""
    if url is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{(settings.data_dir / 'tracker.sqlite3').as_posix()}"
    eng = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
        cur.close()

    return eng


engine = make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
