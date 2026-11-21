"""Domain-free notification interface. Nothing in app.notify may import vehicle code."""
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

log = logging.getLogger("notify")


@dataclass(frozen=True)
class Action:
    label: str
    callback_id: str  # at most 64 bytes (Telegram limit)


class Notifier(Protocol):
    def send(self, title: str, body: str, actions: list[Action] | None = None,
             recipient: str | None = None) -> None:
        """Deliver one message to `recipient` (notifier-specific address; None = the notifier's default).
        Raise on failure so the outbox can retry."""


class LogNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, list[Action]]] = []
        self.recipients: list[str | None] = []

    def send(self, title: str, body: str, actions: list[Action] | None = None,
             recipient: str | None = None) -> None:
        self.sent.append((title, body, actions or []))
        self.recipients.append(recipient)
        log.info("NOTIFY to=%s %s | %s | actions=%s", recipient, title, body, [a.label for a in actions or []])


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramNotifier:
    def __init__(self, token: str, default_chat_ids: list[int] | None = None,
                 client: httpx.Client | None = None) -> None:
        self.token = token
        self.default_chat_ids = default_chat_ids or []
        self.client = client or httpx.Client(timeout=15)

    def send(self, title: str, body: str, actions: list[Action] | None = None,
             recipient: str | None = None) -> None:
        if recipient and recipient.startswith("telegram:"):
            recipient = recipient.split(":", 1)[1]
        chat_ids = [int(recipient)] if recipient else self.default_chat_ids
        if not chat_ids:
            # never report success for a message nobody received; the outbox keeps it for a retry
            raise ValueError("no Telegram chat to send to")
        payload: dict = {"parse_mode": "HTML", "text": f"<b>{_esc(title)}</b>\n{_esc(body)}"}
        if actions:
            payload["reply_markup"] = {"inline_keyboard": [
                [{"text": a.label, "callback_data": a.callback_id} for a in actions]]}
        for chat_id in chat_ids:
            r = self.client.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                 json={**payload, "chat_id": chat_id})
            r.raise_for_status()


DISCORD_API = "https://discord.com/api/v10"


class DiscordNotifier:
    """Sends direct messages through Discord's REST API (the bot itself runs on the gateway elsewhere).
    `recipient` is a Discord user id; the token travels in a header, never in a URL."""

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=15, headers={"Authorization": f"Bot {token}"})
        self._dm_channels: dict[str, str] = {}

    def _dm_channel(self, user_id: str) -> str:
        if user_id not in self._dm_channels:
            r = self.client.post(f"{DISCORD_API}/users/@me/channels", json={"recipient_id": user_id})
            r.raise_for_status()
            self._dm_channels[user_id] = r.json()["id"]
        return self._dm_channels[user_id]

    def send(self, title: str, body: str, actions: list[Action] | None = None,
             recipient: str | None = None) -> None:
        if recipient and recipient.startswith("discord:"):
            recipient = recipient.split(":", 1)[1]
        if not recipient or not recipient.isdigit():
            raise ValueError("no Discord user to send to")
        payload: dict = {"content": f"**{title}**\n{body}"[:2000], "allowed_mentions": {"parse": []}}
        if actions:
            # style 2 = grey button; custom_id carries the same callback string the Telegram buttons use
            payload["components"] = [{"type": 1, "components": [
                {"type": 2, "style": 2, "label": a.label[:80], "custom_id": a.callback_id} for a in actions[:5]]}]
        r = self.client.post(f"{DISCORD_API}/channels/{self._dm_channel(recipient)}/messages", json=payload)
        r.raise_for_status()


class RoutingNotifier:
    """Picks the notifier from the recipient's prefix: "telegram:123" or "discord:456"."""

    def __init__(self, notifiers: dict[str, Notifier]) -> None:
        self.notifiers = notifiers

    def send(self, title: str, body: str, actions: list[Action] | None = None,
             recipient: str | None = None) -> None:
        channel = (recipient or "").split(":", 1)[0]
        if channel.isdigit() and "telegram" in self.notifiers:  # rows queued before channels had prefixes
            channel = "telegram"
        notifier = self.notifiers.get(channel)
        if notifier is None:
            raise ValueError(f"no chat app set up for {channel or 'this message'}")
        notifier.send(title, body, actions, recipient)
