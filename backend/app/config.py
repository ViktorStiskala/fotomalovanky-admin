"""Application configuration using pydantic-settings."""

import json

from pydantic import Field, computed_field
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

    # S3 Storage (MinIO/R2/AWS S3) - all required, no fallbacks
    s3_endpoint: str  # e.g., "http://minio:9000" for MinIO, R2 endpoint for production
    s3_bucket: str = "fotomalovanky"
    s3_region: str = "auto"
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_force_path_style: bool = True  # True for MinIO/R2
    s3_public_url: str  # MANDATORY - public URL for file access (no fallbacks)

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

    # CORS origins - stored as string to avoid pydantic-settings JSON parsing
    # Supports comma-separated values or JSON array format
    backend_cors_origins_str: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="BACKEND_CORS_ORIGINS",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def backend_cors_origins(self) -> list[str]:
        """Parse CORS origins from string (comma-separated or JSON array)."""
        v = self.backend_cors_origins_str
        if not v:
            return []
        if v.startswith("["):
            result: list[str] = json.loads(v)
            return result
        return [origin.strip() for origin in v.split(",") if origin.strip()]


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings loads from env
