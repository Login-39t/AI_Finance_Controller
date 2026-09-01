"""Application settings.

Every environment variable the service reads is declared here, once.

Secrets have no defaults. A missing `JWT_SECRET` stops the process at
startup with a clear message rather than at the first login attempt, and a
missing `ANTHROPIC_API_KEY` stops it at startup *when AI is enabled*
rather than in front of an audience during a demo.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Runtime ----------------------------------------------------------
    environment: Literal["local", "staging", "production"] = "local"
    debug: bool = False
    api_prefix: str = "/v1"

    # -- Database ---------------------------------------------------------
    # asyncpg, always. A synchronous driver anywhere in the request path
    # blocks the event loop and stalls the run-progress poll exactly when
    # the user is watching it.
    database_url: str = "postgresql+asyncpg://ledgergraph:ledgergraph@localhost:5432/ledgergraph"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # -- Auth -------------------------------------------------------------
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    # -- CORS -------------------------------------------------------------
    # Exact origin, never a wildcard. Browsers silently ignore a wildcard
    # once credentials are involved, which reads as "auth is broken in
    # production" on the day you can least afford to debug it.
    frontend_origin: str = "http://localhost:3000"

    # -- Business rules ---------------------------------------------------
    business_timezone: str = "Asia/Kolkata"
    base_currency: str = "INR"
    ruleset_version: str = "rules@1.4.0"

    # -- AI ---------------------------------------------------------------
    ai_enabled: bool = False
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5"
    ai_prompt_version: str = "investigate@v1"

    @field_validator("anthropic_api_key")
    @classmethod
    def _key_required_when_ai_enabled(cls, v: str | None, info) -> str | None:
        if info.data.get("ai_enabled") and not v:
            raise ValueError(
                "AI_ENABLED is true but ANTHROPIC_API_KEY is unset. "
                "Set the key, or set AI_ENABLED=false to run without investigations."
            )
        return v

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings are read once per process and cached.

    Cached so a config read is never a surprise cost inside a request, and
    so a malformed environment fails once at import rather than randomly
    later.
    """
    return Settings()  # type: ignore[call-arg]
