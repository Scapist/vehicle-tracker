from app.config import settings
from app.notify.base import LogNotifier, Notifier, TelegramNotifier

_log = LogNotifier()


def allowed_chat_ids() -> list[int]:
    return [int(x) for x in settings.telegram_allowed_chat_ids.replace(";", ",").split(",") if x.strip()]


def get_notifier() -> Notifier:
    if settings.notifier == "telegram" and settings.telegram_bot_token and allowed_chat_ids():
        return TelegramNotifier(settings.telegram_bot_token, allowed_chat_ids())
    return _log
