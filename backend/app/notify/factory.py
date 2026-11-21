import logging

from app.config import settings
from app.notify.base import DiscordNotifier, LogNotifier, Notifier, RoutingNotifier, TelegramNotifier

log = logging.getLogger("notify")
_log = LogNotifier()


def _ids(raw: str, name: str) -> list[int]:
    ids = []
    for x in raw.replace(";", ",").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            ids.append(int(x))
        except ValueError:
            log.warning("Ignoring invalid %s entry %r", name, x)
    return ids


def allowed_chat_ids() -> list[int]:
    return _ids(settings.telegram_allowed_chat_ids, "TELEGRAM_ALLOWED_CHAT_IDS")


def allowed_discord_ids() -> list[int]:
    return _ids(settings.discord_allowed_user_ids, "DISCORD_ALLOWED_USER_IDS")


def available_channels() -> list[str]:
    """Chat apps that are set up on this server (their bot token is configured)."""
    out = []
    if settings.telegram_bot_token:
        out.append("telegram")
    if settings.discord_bot_token:
        out.append("discord")
    return out


_cache: dict[tuple[str, str], Notifier] = {}


def get_notifier() -> Notifier:
    """Built once per set of tokens, so HTTP connections and Discord DM channels are reused."""
    if not settings.live_notifications:
        return _log
    key = (settings.telegram_bot_token, settings.discord_bot_token)
    if key not in _cache:
        _cache.clear()
        _cache[key] = _build()
    return _cache[key]


def _build() -> Notifier:
    senders: dict[str, Notifier] = {}
    # no default chats: every alert names the chat of the account it belongs to
    if settings.telegram_bot_token:
        senders["telegram"] = TelegramNotifier(settings.telegram_bot_token)
    if settings.discord_bot_token:
        senders["discord"] = DiscordNotifier(settings.discord_bot_token)
    return RoutingNotifier(senders) if senders else _log
