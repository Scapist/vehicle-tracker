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
    def send(self, title: str, body: str, actions: list[Action] | None = None) -> None:
        """Deliver one message. Raise on failure so the outbox can retry."""


class LogNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, list[Action]]] = []

    def send(self, title: str, body: str, actions: list[Action] | None = None) -> None:
        self.sent.append((title, body, actions or []))
        log.info("NOTIFY %s | %s | actions=%s", title, body, [a.label for a in actions or []])


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramNotifier:
    def __init__(self, token: str, chat_ids: list[int], client: httpx.Client | None = None) -> None:
        self.token = token
        self.chat_ids = chat_ids
        self.client = client or httpx.Client(timeout=15)

    def send(self, title: str, body: str, actions: list[Action] | None = None) -> None:
        payload: dict = {"parse_mode": "HTML", "text": f"<b>{_esc(title)}</b>\n{_esc(body)}"}
        if actions:
            payload["reply_markup"] = {"inline_keyboard": [
                [{"text": a.label, "callback_data": a.callback_id} for a in actions]]}
        for chat_id in self.chat_ids:
            r = self.client.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                 json={**payload, "chat_id": chat_id})
            r.raise_for_status()
