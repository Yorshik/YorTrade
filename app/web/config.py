from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    TG_TOKEN: str = Field("", alias="TG_TOKEN")
    TG_API_URL: str = Field("https://api.telegram.org", alias="TG_API_URL")

    RABBIT_DSN: str = Field("amqp://guest:guest@localhost/", alias="RABBIT_DSN")
    REDIS_DSN: str = Field("redis://localhost:6379/0", alias="REDIS_DSN")
    DATABASE_DSN: str = Field("postgresql+asyncpg://postgres:postgres@localhost:5432/app", alias="DATABASE_DSN")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def setup_config(app, config_path):
    app.config = Config(_env_file=config_path)
