"""Environment-backed settings for the Telegram bot process."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    API_BASE_URL: str = "http://localhost:8000"
    GROQ_API_KEY: str
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = BotSettings()
