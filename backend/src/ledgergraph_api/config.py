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
    # Which Repository implementation to install at startup.
    #
    # Explicit rather than "postgres if DATABASE_URL is reachable".
    # Auto-detection would mean a database blip at boot silently
    # downgrades a deployment to a non-durable in-memory store that
    # accepts every write and loses it - which is far worse than
    # refusing to start.
    persistence: Literal["memory", "postgres"] = "memory"
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
    ai_provider: Literal[
        "gemini", "groq", "bedrock", "openai_compatible", "ollama"
    ] = "gemini"
    ai_api_key: str | None = None
    # Pinned, not an alias, so a demo behaves the same tomorrow as today.
    # Google retires models on a schedule and a retired one answers 404
    # ("no longer available to new users") rather than degrading - if
    # that happens, `gemini-flash-latest` always resolves to a current
    # one, at the cost of reproducibility.
    ai_model: str = "gemini-3.6-flash"
    # Only for openai_compatible / ollama; the hosted providers know their own.
    ai_base_url: str | None = None
    # Bedrock only. Model availability is per-region and the model id
    # usually needs a cross-region inference prefix (us.anthropic...),
    # so both have to be stated rather than guessed.
    aws_region: str = "us-east-1"
    ai_prompt_version: str = "investigate@v1"
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 1

    @field_validator("ai_api_key")
    @classmethod
    def _key_required_when_ai_enabled(cls, v: str | None, info) -> str | None:
        # Two providers are exempt, for different reasons: Ollama runs
        # locally with no key at all, and Bedrock authenticates with AWS
        # credentials that boto3 resolves from the environment or an
        # instance role. Demanding AI_API_KEY for Bedrock would make the
        # instance-role case - the one with no long-lived secret, and so
        # the better one - impossible to configure.
        keyless = {"ollama", "bedrock"}
        provider = info.data.get("ai_provider")
        if info.data.get("ai_enabled") and provider not in keyless and not v:
            raise ValueError(
                f"AI_ENABLED is true and AI_PROVIDER is {provider!r}, but AI_API_KEY is unset. "
                "Set the key, set AI_PROVIDER=ollama to run a local model, "
                "or set AI_ENABLED=false to run without investigations."
            )
        return v

    @field_validator("database_url")
    @classmethod
    def _normalise_driver(cls, v: str) -> str:
        """Force the async driver onto whatever the platform hands us.

        Managed Postgres providers - Render, Heroku, Neon, Railway - emit
        a bare `postgresql://` URL, and one of them still emits the
        legacy `postgres://`. SQLAlchemy resolves a driverless
        `postgresql://` to **psycopg2**, which is synchronous, so
        `create_async_engine` raises `InvalidRequestError` on the first
        connection.

        The failure mode is the bad kind: everything works locally, where
        `.env` names the driver explicitly, and the service dies on its
        first request in production. Normalising here means the platform
        can hand over whatever shape it likes.

        `alembic/env.py` reads this value and swaps `+asyncpg` for
        `+psycopg`, so migrations get their synchronous driver from the
        same single source.
        """
        if v.startswith("postgres://"):
            # Removed from SQLAlchemy in 1.4; still emitted by Heroku.
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    @field_validator("persistence")
    @classmethod
    def _production_needs_a_database(cls, v: str, info) -> str:
        if info.data.get("environment") == "production" and v != "postgres":
            raise ValueError(
                "PERSISTENCE=memory in production. The in-memory store has no "
                "durability, no concurrent writers, and none of the schema's "
                "constraints or triggers - it would accept every decision and "
                "lose them on the next restart. Set PERSISTENCE=postgres."
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
