import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import records, reports, rules, tires, vehicles
from app.config import settings
from app.feed import status as feed_status

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs, which include the Telegram bot token
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import scheduler
    from app.bot import runner
    from app.db import SessionLocal
    from app.seed import seed_service_types

    run_migrations()
    with SessionLocal() as db:
        seed_service_types(db)
    sched = scheduler.start()
    bot = runner.start()
    yield
    sched.shutdown(wait=False)
    if bot:
        bot.stop()


app = FastAPI(title="Vehicle Tracker", lifespan=lifespan)

api = APIRouter(prefix="/api/v1")
for r in (vehicles.router, records.router, rules.router, tires.router, reports.router, feed_status.router):
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
