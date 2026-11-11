import logging

from app.config import settings
from app.notify.base import LogNotifier, Notifier, TelegramNotifier

log = logging.getLogger("notify")
_log = LogNotifier()


def allowed_chat_ids() -> list[int]:
    ids = []
    for x in settings.telegram_allowed_chat_ids.replace(";", ",").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            ids.append(int(x))
        except ValueError:
            log.warning("Ignoring invalid TELEGRAM_ALLOWED_CHAT_IDS entry %r", x)
    return ids


def get_notifier() -> Notifier:
    if settings.notifier == "telegram" and settings.telegram_bot_token:
        # no default chats: every alert names the chat of the account it belongs to
        return TelegramNotifier(settings.telegram_bot_token)
    return _log
