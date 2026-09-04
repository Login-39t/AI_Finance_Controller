"""FastAPI application factory.

Router order and middleware placement are deliberate:

* health endpoints are mounted *outside* the `/v1` prefix and require no
  auth, so a platform health check never depends on a token;
* CORS uses an exact origin with credentials enabled, because the refresh
  token travels as a cookie and a wildcard origin is silently ignored by
  browsers once credentials are involved;
* error handlers are registered before routers so that a failure during
  routing still produces `application/problem+json`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Settings, get_settings
from .db import dispose_engine, get_sessionmaker
from .errors import register_error_handlers
from .routers import auth, exceptions, health, imports, matches, reports, runs
from .store import set_repository


def _configure_logging(settings: Settings) -> None:
    """Structured JSON logs, so every line for a run is greppable by run_id."""
    log_level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(format="%(message)s", level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            (structlog.dev.ConsoleRenderer() if settings.is_local
             else structlog.processors.JSONRenderer()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log = structlog.get_logger()
    log.info(
        "api.start",
        version=__version__,
        environment=settings.environment,
        ruleset=settings.ruleset_version,
        ai_enabled=settings.ai_enabled,
    )
    # The database is not probed here on purpose when running on the
    # in-memory store: startup must not depend on it, and /readyz
    # reports its state instead. With PERSISTENCE=postgres it is a hard
    # dependency and failing loudly here is correct - a service that
    # silently falls back to a non-durable store would accept every
    # write and lose it.
    if settings.persistence == "postgres":
        from .store_postgres import bootstrap

        set_repository(await bootstrap(get_sessionmaker()))
        log.info("api.persistence", backend="postgres")
    else:
        log.info(
            "api.persistence", backend="memory",
            warning="non-durable; no constraints or triggers",
        )

    seeded = await auth.seed_demo_users()
    if seeded:
        log.info("api.demo_users_seeded", count=seeded)

    promoted = await auth.bootstrap_admin()
    if promoted:
        log.info("api.admin_bootstrapped", email=promoted)

    yield
    await dispose_engine()
    log.info("api.stop")


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings)

    app = FastAPI(
        title="TallyProof API",
        version=__version__,
        description=(
            "Reconciliation and exception investigation across payments, settlements, "
            "bank, invoices, and ledger. Money crosses this API as strings of minor units."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-Id"],
    )

    register_error_handlers(app)

    # Ops endpoints live at the root, unversioned and unauthenticated.
    app.include_router(health.router)

    # Domain routers.
    app.include_router(auth.router)
    app.include_router(imports.router)
    app.include_router(runs.router)
    app.include_router(exceptions.router)
    app.include_router(matches.router)
    app.include_router(reports.router)

    return app


app = create_app()
