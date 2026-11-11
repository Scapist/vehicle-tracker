import datetime as dt
from zoneinfo import ZoneInfo

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.seed import seed_demo, seed_service_types

NOW = dt.datetime(2026, 11, 11, 12, 0, tzinfo=ZoneInfo("America/Toronto"))
TODAY = NOW.date()


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    with sessionmaker(eng, expire_on_commit=False)() as session:
        seed_service_types(session)
        yield session


@pytest.fixture
def demo(db):
    seed_demo(db, TODAY)
    return db


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def demo_client(demo, client):
    return client
