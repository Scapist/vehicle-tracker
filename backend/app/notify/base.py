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
