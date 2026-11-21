import httpx
import pytest
from sqlalchemy import select

from app import models as m
from app.bot import discord_runner as dr
from app.bot import logic
from app.config import settings
from app.evaluator import evaluate, resolve_recipient
from app.notify.base import Action, DiscordNotifier, RoutingNotifier
from app.nudge import queue_nudges
from tests.conftest import CHAT_ID, make_user, signed_in

DISCORD_ID = 123456789012345678


@pytest.fixture(autouse=True)
def fresh_link_limits():
    logic._link_attempts.clear()


def test_link_with_a_code_from_settings(db, user):
    code = signed_in(db).post("/api/v1/auth/link-code").json()["code"]
    assert "isn't linked" in dr.reply_for_message(db, DISCORD_ID, "84500").text
    assert "wrong or expired" in dr.reply_for_message(db, DISCORD_ID, "!link ZZZZZZZZ").text
    assert "Linked to Me" in dr.reply_for_message(db, DISCORD_ID, f"!link {code.lower()}").text
    assert logic.user_for(db, "discord", DISCORD_ID).id == user.id
    assert db.get(m.User, user.id).telegram_chat_id == CHAT_ID  # Telegram stays linked too
    me = signed_in(db).get("/api/v1/auth/me").json()["user"]
    assert me["discord_linked"] and me["telegram_linked"]


def test_linking_moves_a_discord_account_and_is_rate_limited(db, user):
    other = make_user(db, "b@example.com", "B", owner=False, chat_id=None)
    for u in (user, other):
        code = signed_in(db, u.email).post("/api/v1/auth/link-code").json()["code"]
        dr.reply_for_message(db, DISCORD_ID, f"/link {code}")
    assert logic.user_for(db, "discord", DISCORD_ID).id == other.id  # one Discord account, one tracker account
    assert db.get(m.User, user.id).discord_user_id is None
    for _ in range(logic.LINK_ATTEMPTS):
        dr.reply_for_message(db, 42, "!link WRONG")
    assert "Too many tries" in dr.reply_for_message(db, 42, "!link WRONG").text


def test_linked_user_logs_km_and_commands(demo, user):
    user.discord_user_id = DISCORD_ID
    demo.commit()
    reply = dr.reply_for_message(demo, DISCORD_ID, "civic 90000")
    assert "90,000" in reply.text or reply.buttons
    assert "km" in dr.reply_for_message(demo, DISCORD_ID, "!vehicles").text
    assert "!due" in dr.reply_for_message(demo, DISCORD_ID, "!help").text
    assert "don't know" in dr.reply_for_message(demo, DISCORD_ID, "!bogus").text


def test_parse_command():
    assert dr.parse_command("!link abc") == ("link", ["abc"])
    assert dr.parse_command("/DUE") == ("due", [])
    assert dr.parse_command("84500") is None
    assert dr.parse_command("!") == ("", [])  # used to crash


def test_bare_prefix_gets_help(db, user):
    user.discord_user_id = DISCORD_ID
    db.commit()
    assert "don't know" in dr.reply_for_message(db, DISCORD_ID, "!").text


def test_notifier_fails_closed(monkeypatch):
    for value, live in (("log", False), ("", False), ("off", False), ("Log", False), ("telegram", True),
                        ("chat", True), ("Discord", True)):
        monkeypatch.setattr(settings, "notifier", value)
        assert settings.live_notifications is live, value


def test_allowed_user_ids(monkeypatch):
    assert dr.allowed(5)
    monkeypatch.setattr(settings, "discord_allowed_user_ids", "7, 8")
    assert dr.allowed(7) and not dr.allowed(5)


def test_discord_notifier_opens_dm_once_and_sends_buttons():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.url.path, request.headers.get("authorization"), request.content))
        if request.url.path.endswith("/users/@me/channels"):
            return httpx.Response(200, json={"id": "999"})
        return httpx.Response(200, json={"id": "1"})

    client = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bot tok"})
    n = DiscordNotifier("tok", client=client)
    n.send("Civic: oil", "due", [Action("Done today", "done:rule:1")], recipient=f"discord:{DISCORD_ID}")
    n.send("again", "x", recipient=str(DISCORD_ID))
    paths = [c[0] for c in calls]
    assert paths == ["/api/v10/users/@me/channels", "/api/v10/channels/999/messages",
                     "/api/v10/channels/999/messages"]
    assert all("tok" not in p for p in paths) and calls[0][1] == "Bot tok"
    assert b'"custom_id":"done:rule:1"' in calls[1][2].replace(b" ", b"")
    with pytest.raises(ValueError):
        n.send("t", "b", recipient=None)


def test_discord_notifier_raises_for_retry():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        DiscordNotifier("tok", client=client).send("t", "b", recipient="discord:1")


def test_routing_by_prefix():
    class Rec:
        def __init__(self):
            self.to = []

        def send(self, title, body, actions=None, recipient=None):
            self.to.append(recipient)

    tg, dc = Rec(), Rec()
    r = RoutingNotifier({"telegram": tg, "discord": dc})
    r.send("t", "b", recipient="discord:5")
    r.send("t", "b", recipient="telegram:6")
    r.send("t", "b", recipient="7")  # old row
    assert dc.to == ["discord:5"] and tg.to == ["telegram:6", "7"]
    with pytest.raises(ValueError):
        RoutingNotifier({"telegram": tg}).send("t", "b", recipient="discord:5")


def test_preferred_alert_app(db, user, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "1:x")
    monkeypatch.setattr(settings, "discord_bot_token", "y")
    c = signed_in(db)
    assert resolve_recipient(db, f"user:{user.id}") == f"telegram:{CHAT_ID}"
    assert c.put("/api/v1/auth/alert-channel", json={"channel": "discord"}).status_code == 409  # not linked
    user.discord_user_id = DISCORD_ID
    db.commit()
    assert c.put("/api/v1/auth/alert-channel", json={"channel": "discord"}).json()["alert_channel"] == "discord"
    assert resolve_recipient(db, f"user:{user.id}") == f"discord:{DISCORD_ID}"
    # Discord taken off this server: fall back to Telegram rather than hold the alert
    monkeypatch.setattr(settings, "discord_bot_token", "")
    assert resolve_recipient(db, f"user:{user.id}") == f"telegram:{CHAT_ID}"
    monkeypatch.setattr(settings, "discord_bot_token", "y")
    assert c.delete("/api/v1/auth/discord").status_code == 204
    assert db.get(m.User, user.id).alert_channel is None
    assert resolve_recipient(db, f"user:{user.id}") == f"telegram:{CHAT_ID}"
    assert c.put("/api/v1/auth/alert-channel", json={"channel": "sms"}).status_code == 422


def test_discord_only_user_gets_alerts_and_nudges(demo, user, monkeypatch):
    monkeypatch.setattr(settings, "discord_bot_token", "y")
    user.telegram_chat_id = None
    user.discord_user_id = DISCORD_ID
    demo.commit()
    evaluate(demo)
    assert resolve_recipient(demo, f"user:{user.id}") == f"discord:{DISCORD_ID}"
    queue_nudges(demo)  # the demo odometer may or may not be quiet; it must not skip a Discord-only user
    rows = demo.scalars(select(m.NotificationOutbox)).all()
    assert rows and all(r.recipient == f"user:{user.id}" for r in rows)


def test_discord_receipt_note(demo, user):
    from tests.test_mcp import PNG

    reply = logic.handle_attachment(demo, user, "r.png", PNG, channel="discord")
    assert reply.text
    rec = demo.scalars(select(m.ServiceRecord).order_by(m.ServiceRecord.id.desc())).first()
    assert rec.notes in (None, "Receipt only (from Discord)") or rec.attachments
