"""Application configuration using pydantic-settings."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # Load root .env first, then backend/.env (overrides)
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra variables from root .env (POSTGRES_*, etc.)
    )

    # Database
    database_url: str = "postgresql+asyncpg://fotomalovanky:fotomalovanky@localhost:5432/fotomalovanky"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Mercure
    mercure_url: str  # Required - set via MERCURE_URL env var
    mercure_publisher_jwt_key: str = "change-me-publisher-secret-key"

    # Shopify
    shopify_store_url: str = ""
    shopify_store_handle: str = ""  # e.g., "aqi8it-7n" for admin URL construction
    shopify_access_token: str = ""
    shopify_webhook_secret: str = ""

    # Storage
    storage_path: str = "/data/images"

    # RunPod
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""
    runpod_api_url: str = "https://api.runpod.ai/v2"
    runpod_poll_interval: float = 3.0
    runpod_timeout: int = 600

    # Vectorizer.ai
    vectorizer_api_key: str = ""
    vectorizer_api_secret: str = ""
    vectorizer_url: str = "https://vectorizer.ai/api/v1/vectorize"

    # Processing defaults
    default_megapixels: float = 1.0
    default_steps: int = 4
    min_image_size: int = 1200

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


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings loads from env
