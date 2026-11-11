import datetime as dt
import os
from zoneinfo import ZoneInfo

# TestClient sends Host: testserver; must be set before app.config is imported
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app import models as m
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.seed import seed_demo, seed_service_types

NOW = dt.datetime(2026, 11, 11, 12, 0, tzinfo=ZoneInfo("America/Toronto"))
TODAY = NOW.date()
PASSWORD = "test-password-1"
CHAT_ID = 111


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture(autouse=True)
def clean_auth_state():
    auth._failures.clear()
    auth._link_codes.clear()
    auth._setup_code = None
    yield
    auth._failures.clear()


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


def make_user(db, email="me@example.com", name="Me", owner=True, chat_id=CHAT_ID) -> m.User:
    u = m.User(email=email, name=name, password_hash=auth.hash_password(PASSWORD), is_owner=owner,
               telegram_chat_id=chat_id)
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def user(db):
    return make_user(db)


@pytest.fixture
def demo(db, user):
    seed_demo(db, TODAY, user)
    return db


def signed_in(db, email="me@example.com") -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def client(db, user):
    yield signed_in(db)
    app.dependency_overrides.clear()


@pytest.fixture
def demo_client(demo, client):
    return client
