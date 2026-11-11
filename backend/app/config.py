from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("../data")
    static_dir: Path = Path("../frontend/dist")
    timezone: str = "America/Toronto"
    notifier: str = "log"  # "log" | "telegram"
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""
    # Host names/IPs the app answers to (blocks DNS rebinding). Add your LAN IP or hostname.
    allowed_hosts: str = "localhost,127.0.0.1"
    secret_key: str = ""  # signs session cookies; generated into data/secret_key when empty

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


settings = Settings()
