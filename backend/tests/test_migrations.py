import sqlite3

from alembic import command
from alembic.config import Config

from app.config import settings
from app.main import BACKEND_DIR, run_migrations


def _cfg() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


COUNTED = ["vehicle", "odometer_reading", "service_record", "service_record_item", "reminder_rule", "tire_set"]


def test_upgrade_keeps_every_row_and_backs_up_first(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    command.upgrade(_cfg(), "0001")
    db = tmp_path / "tracker.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO vehicle (id, nickname, make, model, year, archived) VALUES (1,'civic','Honda','Civic',2026,0)")
        c.execute("INSERT INTO service_type (id, key, name, default_soon_km, default_soon_days) VALUES (1,'oil','Oil',1000,30)")
        c.executemany("INSERT INTO odometer_reading (vehicle_id, km, recorded_at, source, is_correction, invalidated)"
                      " VALUES (1, ?, '2026-11-11 12:00:00', 'ui', 0, 0)", [(k,) for k in (127000, 130000, 131000)])
        c.execute("INSERT INTO service_record (id, vehicle_id, date, odometer_km, cost_cents) VALUES (1,1,'2026-11-11',131000,0)")
        c.execute("INSERT INTO service_record_item (service_record_id, service_type_id) VALUES (1,1)")
        c.execute("INSERT INTO reminder_rule (vehicle_id, service_type_id, interval_km, soon_km, soon_days, enabled)"
                  " VALUES (1,1,8000,1000,30,1)")
        c.execute("INSERT INTO tire_set (vehicle_id, label, season, retired) VALUES (1,'Winter','winter',0)")
        before = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COUNTED}

    run_migrations()  # the real startup path: backup, then upgrade with foreign keys off

    with sqlite3.connect(db) as c:
        after = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COUNTED}
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006"
        assert c.execute("SELECT user_id FROM vehicle").fetchone() == (None,)  # claimed at owner setup
    assert after == before and before["odometer_reading"] == 3
    backups = list((tmp_path / "backups").glob("tracker-before-0006-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as c:
        assert c.execute("SELECT count(*) FROM odometer_reading").fetchone()[0] == 3

    run_migrations()  # already at head: no second backup
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_downgrade_also_keeps_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    command.upgrade(_cfg(), "head")
    with sqlite3.connect(tmp_path / "tracker.sqlite3") as c:
        c.execute("INSERT INTO vehicle (id, nickname, make, model, year, archived) VALUES (1,'civic','Honda','Civic',2026,0)")
        c.execute("INSERT INTO odometer_reading (vehicle_id, km, recorded_at, source, is_correction, invalidated)"
                  " VALUES (1, 5, '2026-11-11 12:00:00', 'ui', 0, 0)")
    command.downgrade(_cfg(), "0001")
    with sqlite3.connect(tmp_path / "tracker.sqlite3") as c:
        assert c.execute("SELECT count(*) FROM odometer_reading").fetchone()[0] == 1
