"""Application settings.

Every environment variable the service reads is declared here, once.

Secrets have no defaults. A missing `JWT_SECRET` stops the process at
startup with a clear message rather than at the first login attempt, and a
missing `AI_API_KEY` stops it at startup *when AI is enabled*
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

    # Four accounts, one per role, so the RBAC boundary can be shown
    # rather than described. Guarded by a validator below because a
    # known-password account in production is not a demo convenience,
    # it is an open door.
    seed_demo_users: bool = True
    demo_password: str = "ledgergraph-demo-2026"

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
    # Provider-neutral on purpose. The investigation layer needs one thing
    # from a model - schema-constrained JSON - and several providers do
    # that on a free tier. Naming the vendor in the config would bake a
    # billing decision into the code, so the provider is data.
    #
    # This is cheap to keep flexible precisely because the architecture
    # already distrusts the model: verify.py checks every citation against
    # the packet and every number against what the engine computed, and
    # policy.py gates resolution deterministically. The model contributes
    # prose and a label, never an outcome - so a smaller free model is a
    # cost decision here, not a correctness one.
    ai_enabled: bool = False
    ai_provider: Literal["gemini", "groq", "openai_compatible", "ollama"] = "gemini"
    ai_api_key: str | None = None
    ai_model: str = "gemini-2.5-flash"
    # Only for openai_compatible / ollama; the hosted providers know their own.
    ai_base_url: str | None = None
    ai_prompt_version: str = "investigate@v1"
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 1

    @field_validator("ai_api_key")
    @classmethod
    def _key_required_when_ai_enabled(cls, v: str | None, info) -> str | None:
        # Ollama runs locally with no key, so it is exempt.
        provider = info.data.get("ai_provider")
        if info.data.get("ai_enabled") and provider != "ollama" and not v:
            raise ValueError(
                f"AI_ENABLED is true and AI_PROVIDER is {provider!r}, but AI_API_KEY is unset. "
                "Set the key, set AI_PROVIDER=ollama to run a local model, "
                "or set AI_ENABLED=false to run without investigations."
            )
        return v

    @field_validator("seed_demo_users")
    @classmethod
    def _no_demo_users_in_production(cls, v: bool, info) -> bool:
        if v and info.data.get("environment") == "production":
            raise ValueError(
                "SEED_DEMO_USERS is true in production. These accounts have a "
                "password that is published in the README; refusing to create "
                "them. Set SEED_DEMO_USERS=false."
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
