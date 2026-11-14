"""Application settings, read from environment variables (and ``.env`` in development).

Everything configurable lives here so that no other module reads the environment.
Unsafe combinations are rejected at start-up rather than discovered in production.
"""

from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]

_DEV_SECRET = "development-only-secret-do-not-use-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: str = ""
    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5432/tatmaq_dev"
    cors_allowed_origins: str = ""

    # Connections each process may hold open. Lower both on a small database: with
    # the API, the worker and one job running, three processes share the server's limit.
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- authentication -----------------------------------------------------
    # "builtin":  the application's own email-and-password accounts, kept in its database.
    # "supabase": verify Supabase Auth access tokens.
    # "dev":      the built-in accounts with a fixed, published signing secret, so a laptop
    #             needs no configuration. Refused when APP_ENV=production.
    auth_mode: Literal["dev", "builtin", "supabase"] = "supabase"
    # Whether anyone may create an account (built-in sign-in). When false, accounts are
    # created by the administrator with scripts/accounts.py.
    allow_signups: bool = True
    # Optional override for the key that signs built-in session tokens. Left empty, the
    # key is derived from APP_SECRET_KEY, so production needs no second secret.
    dev_jwt_secret: str = ""
    supabase_url: str = ""
    supabase_publishable_key: str = Field(
        "", validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY")
    )
    supabase_secret_key: str = Field(
        "", validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
    )
    jwt_issuer: str = ""
    jwt_audience: str = "authenticated"

    # --- file storage -------------------------------------------------------
    # "local":    files on this server's disk (development, or a host with a persistent volume)
    # "database": files in PostgreSQL itself, for hosts whose disk is wiped on restart
    # "supabase": a private Supabase Storage bucket
    storage_backend: Literal["local", "database", "supabase"] = "local"
    storage_local_dir: Path = REPO_ROOT / "var" / "storage"
    object_storage_bucket: str = "tatmaq-private"

    # --- AI provider (optional) ----------------------------------------------
    # "none" runs the deterministic planner and template narrative: no key needed.
    ai_provider: Literal["none", "openai_compatible", "anthropic"] = "none"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_timeout_seconds: float = 60.0

    # --- limits -------------------------------------------------------------
    max_upload_mb: int = 50
    max_analysis_rows: int = 1_000_000
    max_analysis_columns: int = 200
    max_organisations_per_user: int = 5
    max_active_jobs_per_org: int = 5
    plan_monthly_analysis_jobs: int = 100
    upload_url_ttl_seconds: int = 3600
    download_url_ttl_seconds: int = 300

    # --- background worker --------------------------------------------------
    worker_concurrency: int = 1
    worker_poll_seconds: float = 1.0
    job_timeout_seconds: int = 600
    job_max_memory_mb: int = 1536  # 0 disables the address-space limit
    job_max_attempts: int = 3
    job_heartbeat_seconds: int = 10
    job_stale_after_seconds: int = 60
    work_dir: Path = REPO_ROOT / "var" / "work"

    # --- locale defaults for new organisations --------------------------------
    default_currency: str = "USD"
    default_timezone: str = "Africa/Harare"
    default_date_order: Literal["DMY", "MDY"] = "DMY"

    @model_validator(mode="after")
    def _check(self) -> Settings:
        production = self.app_env == "production"
        if production:
            if self.auth_mode == "dev":
                raise ValueError("AUTH_MODE=dev provides development-only accounts and is refused in production.")
            if len(self.app_secret_key) < 32:
                raise ValueError("APP_SECRET_KEY must be set to at least 32 random characters in production.")
            if not self.cors_origins:
                raise ValueError("CORS_ALLOWED_ORIGINS must list the web app's origin(s) in production.")
        else:
            self.app_secret_key = self.app_secret_key or _DEV_SECRET
            if self.auth_mode == "dev":
                self.dev_jwt_secret = self.dev_jwt_secret or _DEV_SECRET

        if self.auth_mode == "supabase" and not self.supabase_url:
            raise ValueError(
                "AUTH_MODE=supabase needs SUPABASE_URL (or set AUTH_MODE=builtin, or AUTH_MODE=dev for local development)."
            )
        if self.storage_backend == "supabase" and not (self.supabase_url and self.supabase_secret_key):
            raise ValueError("STORAGE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SECRET_KEY.")
        if self.ai_provider != "none" and not (self.ai_api_key and self.ai_model):
            raise ValueError("AI_PROVIDER is set, so AI_API_KEY and AI_MODEL are required (or set AI_PROVIDER=none).")
        if "*" in self.cors_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must list explicit origins; '*' is not accepted.")
        if self.db_pool_size < 1 or self.db_max_overflow < 0:
            raise ValueError("DB_POOL_SIZE must be at least 1 and DB_MAX_OVERFLOW must not be negative.")
        return self

    @property
    def builtin_sign_in(self) -> bool:
        """True when this API keeps the accounts itself (rather than Supabase Auth)."""
        return self.auth_mode in ("dev", "builtin")

    @property
    def session_token_secret(self) -> str:
        """The key that signs built-in session tokens.

        Derived from APP_SECRET_KEY under its own label, so a session token can never be
        confused with a signed file link even though both start from the same secret.
        """
        if self.dev_jwt_secret:
            return self.dev_jwt_secret
        return hmac.new(self.app_secret_key.encode(), b"tatmaq session tokens v1", hashlib.sha256).hexdigest()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def sqlalchemy_url(self) -> str:
        """Accept the plain ``postgresql://`` URLs that hosting dashboards hand out."""
        scheme, separator, rest = self.database_url.partition("://")
        if scheme in ("postgres", "postgresql"):
            scheme = "postgresql+psycopg"
        return f"{scheme}{separator}{rest}"

    @property
    def supabase_issuer(self) -> str:
        return self.jwt_issuer or f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "none"


@lru_cache
def get_settings() -> Settings:
    return Settings()
