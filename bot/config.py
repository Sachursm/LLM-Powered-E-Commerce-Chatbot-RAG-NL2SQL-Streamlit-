"""Environment-backed settings for the Telegram bot process."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    API_BASE_URL: str = "http://localhost:8000"
    GROQ_API_KEY: str
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    CONTINUATION_MODEL: str = "openai/gpt-oss-20b"
    REDIS_URL: str = "redis://localhost:6379/0"
    ROUTER_CONFIDENCE_THRESHOLD: float = Field(default=0.40, ge=0.0, le=1.0)
    # Product photos uploaded through the bot are stored on Cloudinary. Without
    # these, sellers can still paste an image URL.
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None
    CLOUDINARY_FOLDER: str = "sachumart/products"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = BotSettings()
