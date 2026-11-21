from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("../data")
    static_dir: Path = Path("../frontend/dist")
    timezone: str = "America/Toronto"
    # "log" writes alerts to the container log only (testing). "telegram", "discord" or "chat" send them through
    # every chat app whose token is set below. Any other value counts as "log" (fails closed).
    notifier: str = "log"
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""
    discord_bot_token: str = ""
    # optional: Discord user ids the bot answers at all (everyone else is ignored without a reply)
    discord_allowed_user_ids: str = ""
    # MCP server for AI assistants at /mcp. Off unless turned on; "owner" = only the owner may create tokens.
    mcp_enabled: bool = False
    mcp_users: str = "owner"  # "owner" | "all"
    # Host names/IPs the app answers to (blocks DNS rebinding). Add your LAN IP or hostname.
    allowed_hosts: str = "localhost,127.0.0.1"
    secret_key: str = ""  # signs session cookies; generated into data/secret_key when empty

    @property
    def live_notifications(self) -> bool:
        return self.notifier.strip().lower() in {"telegram", "discord", "chat"}

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


settings = Settings()
