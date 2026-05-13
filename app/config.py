from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_allowed_user_id: int | None = None
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5-20250929"
    database_url: str = "postgresql+psycopg://fitness:fitness@db:5432/fitness"
    bodyweight_kg: float = Field(default=78, alias="BODYWEIGHT_KG")
    session_median_power: float = 3161
    tz: str = "Europe/Lisbon"
    web_bind_host: str = "127.0.0.1"
    web_bind_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

