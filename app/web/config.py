from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    TG_TOKEN: str = Field("", alias="TG_TOKEN")
    TG_API_URL: str = Field("https://api.telegram.org", alias="TG_API_URL")
    ADMIN_TG_ID: int = Field(0, alias="ADMIN_TG_ID")
    ADMIN_API_TOKEN: str = Field("", alias="ADMIN_API_TOKEN")
    VK_TOKEN: str = Field("", alias="VK_TOKEN")
    VK_GROUP_ID: int = Field(0, alias="VK_GROUP_ID")
    VK_API_URL: str = Field("https://api.vk.com/method", alias="VK_API_URL")
    VK_API_VERSION: str = Field("5.199", alias="VK_API_VERSION")
    API_AUTH_TTL_HOURS: int = Field(24, alias="API_AUTH_TTL_HOURS", ge=1)
    ADMIN_LOGIN: str = Field("admin", alias="ADMIN_LOGIN")
    ADMIN_PASS: str = Field("admin", alias="ADMIN_PASS")

    RABBIT_DSN: str = Field("amqp://guest:guest@localhost/", alias="RABBIT_DSN")
    REDIS_DSN: str = Field("redis://localhost:6479/0", alias="REDIS_DSN")
    DATABASE_DSN: str = Field("postgresql+asyncpg://postgres:postgres@localhost:5432/app", alias="DATABASE_DSN")
    PREFIX: str = Field("/", alias="PREFIX")
    TG_BOT_USERNAME: str = Field("", alias="TG_BOT_USERNAME")
    MIN_PLAYERS: int = Field(1, alias="MIN_PLAYERS", ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def setup_config(app, config_path):
    app.config = Config(_env_file=config_path)
