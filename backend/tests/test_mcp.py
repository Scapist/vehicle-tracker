import base64
import datetime as dt
import json
from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy import select

from app import mcp_server as ms
from app import models as m
from app.config import settings
from app.main import app
from mcp.server.mcpserver.exceptions import ToolError
from tests.conftest import TODAY, make_user, signed_in

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PROTO = {"mcp-protocol-version": "2025-06-18"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mcp_on(db, monkeypatch):
    monkeypatch.setattr(settings, "mcp_enabled", True)

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(ms, "_session", session)
    ms._upload_links.clear()


def _token(db, user, name="Claude") -> str:
    token = ms.new_token()
    db.add(m.ApiToken(user_id=user.id, name=name, token_hash=ms.hash_token(token)))
    db.commit()
    return token


async def _rpc(c, token, method, params=None):
    h = {"Accept": "application/json, text/event-stream", **PROTO}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return await c.post("/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


# ---------- over HTTP ----------

@pytest.mark.anyio
async def test_needs_a_valid_token_and_works_with_one(demo, user, mcp_on):
    token = _token(demo, user)
    async with ms.running():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
            assert (await _rpc(c, None, "tools/list")).status_code == 401
            assert (await _rpc(c, "vt_wrong", "tools/list")).status_code == 401
            r = await _rpc(c, token, "tools/call", {"name": "list_vehicles", "arguments": {}})
            assert r.status_code == 200, r.text
            result = r.json()["result"]
            assert not result["isError"]
            assert [v["nickname"] for v in result["structuredContent"]["result"]] == ["Civic"]
            tools = {t["name"] for t in (await _rpc(c, token, "tools/list")).json()["result"]["tools"]}
            assert {"log_odometer", "log_service", "attach_receipt", "whats_due"} <= tools
            assert not tools & {"delete_service", "edit_service"}  # nothing destructive
    row = demo.scalar(select(m.ApiToken))
    assert row.last_used_at is not None and row.token_hash != token and token not in row.token_hash


@pytest.mark.anyio
async def test_revoked_token_and_rate_limit(db, user, mcp_on):
    token = _token(db, user)
    db.scalar(select(m.ApiToken)).revoked_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    async with ms.running():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
            assert (await _rpc(c, token, "tools/list")).status_code == 401
            codes = [(await _rpc(c, f"vt_guess{i}", "tools/list")).status_code for i in range(25)]
            assert codes[-1] == 429  # guessing tokens gets locked out like guessing passwords


@pytest.mark.anyio
async def test_off_by_default(db, user):
    assert settings.mcp_enabled is False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        assert (await _rpc(c, _token(db, user), "tools/list")).status_code == 404


def test_member_tokens_follow_mcp_users(db, user, mcp_on, monkeypatch):
    member = make_user(db, "b@example.com", "B", owner=False, chat_id=None)
    token = _token(db, member)
    assert ms.user_for_token(db, token) is None  # default MCP_USERS=owner
    monkeypatch.setattr(settings, "mcp_users", "all")
    assert ms.user_for_token(db, token).id == member.id


# ---------- token API ----------

def test_token_api(db, user, mcp_on):
    c = signed_in(db)
    r = c.post("/api/v1/mcp-tokens", json={"name": "Claude Desktop"})
    assert r.status_code == 201 and r.json()["token"].startswith("vt_")
    listed = c.get("/api/v1/mcp-tokens").json()
    assert [t["name"] for t in listed] == ["Claude Desktop"] and listed[0]["token"] is None  # shown once
    assert c.delete(f"/api/v1/mcp-tokens/{listed[0]['id']}").status_code == 204
    assert c.get("/api/v1/mcp-tokens").json() == []
    assert ms.user_for_token(db, r.json()["token"]) is None

    member = make_user(db, "b@example.com", "B", owner=False, chat_id=None)
    other = signed_in(db, "b@example.com")
    assert other.post("/api/v1/mcp-tokens", json={"name": "x"}).status_code == 403
    assert other.delete(f"/api/v1/mcp-tokens/{listed[0]['id']}").status_code == 404
    assert member


def test_token_api_off(client):
    assert client.post("/api/v1/mcp-tokens", json={"name": "x"}).status_code == 404


# ---------- the tools ----------

def test_read_tools_only_see_your_data(demo, user):
    other = make_user(demo, "b@example.com", "B", owner=False, chat_id=None)
    demo.add(m.Vehicle(nickname="Truck", make="Ford", model="F150", year=2015, user_id=other.id))
    demo.commit()
    assert [v["nickname"] for v in ms.list_vehicles_impl(demo, user)] == ["Civic"]
    with pytest.raises(ToolError, match="No vehicle called 'Truck'"):
        ms.service_history_impl(demo, user, "Truck")
    assert ms.service_history_impl(demo, user, "civic")  # any case
    due = ms.whats_due_impl(demo, user)
    assert due and due[0]["status"] == "overdue"
    assert "Oil change" in ms.list_service_types_impl(demo, user)
    s = ms.spending_impl(demo, user, dt.date(TODAY.year, 1, 1), TODAY)
    assert s["total"] > 0 and s["entries"]


def test_upload_link_dies_with_its_token(demo, user, mcp_on):
    rec_id = ms.log_service_impl(demo, user, "Civic", TODAY, ["Oil change"])["service_id"]
    _token(demo, user)
    row = demo.scalar(select(m.ApiToken))
    path = ms.receipt_upload_link_impl(demo, user, rec_id, "http://testserver", row.id)["url"].removeprefix(
        "http://testserver")
    row.revoked_at = dt.datetime.now(dt.timezone.utc)
    demo.commit()
    r = signed_in(demo).post(path, files={"file": ("r.png", PNG, "image/png")})
    assert r.status_code == 404 and not demo.get(m.ServiceRecord, rec_id).attachments


def test_upload_page_escapes_the_nickname(demo, user, mcp_on):
    demo.scalar(select(m.Vehicle)).nickname = "<b>x</b>"
    demo.commit()
    rec_id = ms.log_service_impl(demo, user, "<b>x</b>", TODAY, ["Oil change"])["service_id"]
    path = ms.receipt_upload_link_impl(demo, user, rec_id, "http://testserver")["url"].removeprefix(
        "http://testserver")
    page = signed_in(demo).get(path).text
    assert "<b>x</b>" not in page and "&lt;b&gt;" in page


@pytest.mark.anyio
async def test_a_good_token_clears_earlier_failures(db, user, mcp_on):
    from app import auth

    token = _token(db, user)
    async with ms.running():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
            for i in range(4):
                await _rpc(c, f"vt_old{i}", "tools/list")
            assert any(k.startswith("mcp:") for k in auth._failures)
            assert (await _rpc(c, token, "tools/list")).status_code == 200
            assert not any(k.startswith("mcp:") for k in auth._failures)


def test_log_odometer_guards(demo, user):
    cur = ms.list_vehicles_impl(demo, user)[0]["current_km"]
    with pytest.raises(ToolError, match="correction=true"):
        ms.log_odometer_impl(demo, user, "Civic", cur - 100)
    with pytest.raises(ToolError, match="confirm_big_jump=true"):
        ms.log_odometer_impl(demo, user, "Civic", cur + 9000)
    with pytest.raises(ToolError, match="only for a reading lower"):
        ms.log_odometer_impl(demo, user, "Civic", cur + 9000, correction=True)  # can't skip the jump check
    assert ms.log_odometer_impl(demo, user, "Civic", cur + 120)["logged_km"] == cur + 120
    fixed = ms.log_odometer_impl(demo, user, "Civic", cur + 50, correction=True)
    assert fixed["readings_marked_wrong"] == 1
    r = demo.scalars(select(m.OdometerReading).order_by(m.OdometerReading.id.desc())).first()
    assert r.source == "mcp"


def test_log_service_and_receipts(demo, user):
    with pytest.raises(ToolError, match="Unknown service name"):
        ms.log_service_impl(demo, user, "Civic", TODAY, ["Flux capacitor"])
    with pytest.raises(ToolError, match="between 0 and"):
        ms.log_service_impl(demo, user, "Civic", TODAY, ["Oil change"], cost=float("nan"))
    cur = ms.list_vehicles_impl(demo, user)[0]["current_km"]
    with pytest.raises(ToolError, match="confirm_big_jump=true"):
        ms.log_service_impl(demo, user, "Civic", TODAY, ["Oil change"], odometer_km=999_999)
    assert ms.list_vehicles_impl(demo, user)[0]["current_km"] == cur  # nothing changed
    with pytest.raises(ToolError, match="future"):
        ms.log_service_impl(demo, user, "Civic", TODAY + dt.timedelta(days=1), ["Oil change"])
    out = ms.log_service_impl(demo, user, "Civic", TODAY, ["oil change"], cost=86.4, vendor="Speedy")
    rec = demo.get(m.ServiceRecord, out["service_id"])
    assert rec.cost_cents == 8640 and rec.vendor == "Speedy" and out["services"] == ["Oil change"]

    with pytest.raises(ToolError, match="Unsupported file type"):
        ms.attach_receipt_impl(demo, user, rec.id, "x.txt", base64.b64encode(b"hello").decode())
    with pytest.raises(ToolError, match="base64"):
        ms.attach_receipt_impl(demo, user, rec.id, "x.png", "not base64!!")
    att = ms.attach_receipt_impl(demo, user, rec.id, "r.png", base64.b64encode(PNG).decode())
    assert att["file"] == "r.png"
    other = make_user(demo, "b@example.com", "B", owner=False, chat_id=None)
    with pytest.raises(ToolError, match="No service"):
        ms.attach_receipt_impl(demo, other, rec.id, "r.png", base64.b64encode(PNG).decode())


def test_upload_link_is_single_use_and_expires(demo, user, mcp_on):
    rec_id = ms.log_service_impl(demo, user, "Civic", TODAY, ["Oil change"])["service_id"]
    link = ms.receipt_upload_link_impl(demo, user, rec_id, "http://testserver/")
    path = link["url"].removeprefix("http://testserver")
    c = signed_in(demo)
    assert "Upload receipt" in c.get(path).text
    bad = c.post(path, files={"file": ("x.txt", b"hello", "text/plain")})
    assert bad.status_code == 422  # a wrong file doesn't burn the link
    ok = c.post(path, files={"file": ("r.png", PNG, "image/png")})
    assert ok.status_code == 200 and "Uploaded" in ok.text
    assert len(demo.get(m.ServiceRecord, rec_id).attachments) == 1
    assert c.post(path, files={"file": ("r.png", PNG, "image/png")}).status_code == 404  # used

    link2 = ms.receipt_upload_link_impl(demo, user, rec_id, "http://testserver")
    token = link2["url"].rsplit("/", 1)[1]
    assert token.startswith("vu_")
    uid, sid, _, tid = ms._upload_links[token]
    ms._upload_links[token] = (uid, sid, 0, tid)  # expired
    assert c.get(f"/receipt-upload/{token}").status_code == 404


def test_tool_schemas_hide_the_context():
    import anyio

    tools = anyio.run(ms.mcp.list_tools)
    by_name = {t.name: t for t in tools}
    assert "ctx" not in json.dumps(by_name["log_service"].input_schema)
    assert set(by_name["log_service"].input_schema["required"]) == {"vehicle", "date", "services"}
