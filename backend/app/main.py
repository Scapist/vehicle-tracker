import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import auth
from app.api import records, reports, rules, tires, vehicles
from app.config import settings
from app.feed import status as feed_status
from app.security import BodySizeLimit, RedactingFormatter, guard

logging.basicConfig(level=logging.INFO)
for _h in logging.getLogger().handlers:
    _h.setFormatter(RedactingFormatter("%(levelname)s:%(name)s:%(message)s"))
# httpx logs full request URLs, which include the Telegram bot token
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    backup_before_migrating(cfg)
    command.upgrade(cfg, "head")


def backup_before_migrating(cfg: Config) -> Path | None:
    """Copy the database (safely, via SQLite's backup API) before applying any pending migration."""
    import sqlite3
    from datetime import datetime

    from alembic.script import ScriptDirectory

    db_path = settings.data_dir / "tracker.sqlite3"
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path) as conn:
        try:
            current = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            current = None
        head = ScriptDirectory.from_config(cfg).get_current_head()
        if current and current[0] == head:
            return None
        dest_dir = settings.data_dir / "backups"
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / f"tracker-before-{head}-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        with sqlite3.connect(dest) as out:
            conn.backup(out)
    logging.getLogger("migrate").warning("database backed up to %s before migrating to %s", dest, head)
    return dest


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import scheduler
    from app.bot import runner
    from app.db import SessionLocal
    from app.seed import seed_service_types

    run_migrations()
    with SessionLocal() as db:
        seed_service_types(db)
        auth.announce_setup(db)
    sched = scheduler.start()
    bot = runner.start()
    yield
    sched.shutdown(wait=False)
    if bot:
        bot.stop()


app = FastAPI(title="Vehicle Tracker", lifespan=lifespan)
# answer only to known host names (DNS rebinding), refuse cross-site writes (CSRF), cap request size,
# require a session for data, and send safe headers
app.middleware("http")(guard)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
app.add_middleware(BodySizeLimit)  # outermost: counts streamed bytes before anything parses them

api = APIRouter(prefix="/api/v1")
for r in (auth.router, vehicles.router, records.router, rules.router, tires.router, reports.router,
          feed_status.router):
    api.include_router(r)
app.include_router(api)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


static_dir = settings.static_dir
if static_dir.is_dir():
    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")
