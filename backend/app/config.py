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


settings = Settings()
