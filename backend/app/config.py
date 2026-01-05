"""Application configuration using pydantic-settings."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://fotomalovanky:fotomalovanky@localhost:5432/fotomalovanky"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Mercure
    mercure_url: str = "http://localhost:3000/.well-known/mercure"
    mercure_publisher_jwt_key: str = "change-me-publisher-secret-key"

    # Shopify
    shopify_store_url: str = ""
    shopify_access_token: str = ""
    shopify_webhook_secret: str = ""

    # Storage
    storage_path: str = "/data/images"

    # Application
    debug: bool = False
    log_level: str = "info"
    timezone: str = "Europe/Prague"
    backend_cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            if v.startswith("["):
                import json

                result: list[str] = json.loads(v)
                return result
            return [i.strip() for i in v.split(",")]
        return v


settings = Settings()
