from alembic import context
from sqlalchemy import text

from app import models  # noqa: F401
from app.db import Base, make_engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # Foreign keys OFF while migrating: batch mode rebuilds tables by drop + rename, which with
    # ON DELETE CASCADE would wipe every child row. Integrity is checked before committing instead.
    engine = make_engine(foreign_keys=False)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
            problems = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            if problems:
                raise RuntimeError(f"Migration left broken references, rolled back: {problems[:5]}")
    engine.dispose()


run_migrations_online()
