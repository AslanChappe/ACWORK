from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────
    api_env: Literal["development", "production"] = "production"
    api_secret_key: str = Field(min_length=32)
    log_level: str = "info"

    # ── Database ───────────────────────────────────────────
    database_url: str  # postgresql+asyncpg://user:pass@host:5432/db

    # Pool settings
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # ── Redis ──────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"  # DB 0 = Celery broker + backend

    # ── Timezone ───────────────────────────────────────────
    timezone: str = "America/Cayenne"

    # ── CORS (prod) ────────────────────────────────────────
    allowed_origins: str = ""  # origines séparées par des virgules, ex: "https://app.domain.com"

    # ── Celery ─────────────────────────────────────────────
    celery_concurrency: int = 4
    celery_task_max_retries: int = 3
    celery_task_retry_backoff: int = 60  # secondes entre chaque retry

    # ── Auth service-to-service ────────────────────────────────
    internal_api_key: str = ""  # clé partagée X-API-Key (vide = désactivé en dev)

    # ── n8n integration ────────────────────────────────────
    n8n_base_url: str = "http://n8n:5678"
    n8n_api_key: str = ""

    # ── Monitoring ─────────────────────────────────────────
    sentry_dsn: str = ""  # laisser vide pour désactiver

    # ── API behaviour ──────────────────────────────────────
    api_version: str = "v1"
    request_timeout: int = 30
    max_workers: int = 4

    @computed_field  # type: ignore[misc]
    @property
    def is_dev(self) -> bool:
        return self.api_env == "development"

    @computed_field  # type: ignore[misc]
    @property
    def api_prefix(self) -> str:
        return f"/api/{self.api_version}"

    @computed_field  # type: ignore[misc]
    @property
    def celery_broker_url(self) -> str:
        return self.redis_url

    @computed_field  # type: ignore[misc]
    @property
    def celery_result_backend(self) -> str:
        return self.redis_url

    @computed_field  # type: ignore[misc]
    @property
    def cors_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS env var into a list. Returns ['*'] in dev."""
        if self.is_dev:
            return ["*"]
        if not self.allowed_origins:
            return []
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
