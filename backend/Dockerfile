# syntax=docker/dockerfile:1
#
# The API image.
#
# Build context is the **repository root**, not backend/ - the service
# imports the three framework-free packages under packages/, and a build
# context that could not see them would produce an image that fails at
# import rather than at build. Build it as:
#
#     docker build -f backend/Dockerfile -t ledgergraph-api .
#
# Two stages: the first installs dependencies with build tooling
# available, the second carries only the resulting site-packages. That
# keeps a compiler out of the runtime image, which is both smaller and
# one fewer thing to patch.

# --------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# argon2-cffi and psycopg build against these when a wheel is unavailable.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Dependency metadata first, so a source-only change does not invalidate
# the dependency layer. This is the difference between a 15-second
# rebuild and a three-minute one.
COPY backend/pyproject.toml backend/pyproject.toml
COPY packages/domain/pyproject.toml packages/domain/pyproject.toml
COPY packages/reconciliation/pyproject.toml packages/reconciliation/pyproject.toml
COPY packages/ai_investigation/pyproject.toml packages/ai_investigation/pyproject.toml

COPY packages/ packages/
COPY backend/ backend/

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ./packages/domain \
                                 ./packages/reconciliation \
                                 ./packages/ai_investigation \
                                 ./backend

# --------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq only - the runtime needs the client library, not the toolchain
# that linked against it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 ledgergraph

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=ledgergraph:ledgergraph db/ db/
COPY --chown=ledgergraph:ledgergraph backend/alembic.ini backend/alembic.ini
COPY --chown=ledgergraph:ledgergraph backend/alembic/ backend/alembic/

# Non-root. A container that runs as root is one container escape away
# from being a root shell on the host.
USER ledgergraph

EXPOSE 8000

# /healthz answers without touching the database on purpose, so this
# reports the process, not its dependencies. /readyz reports those, and
# the platform's own readiness probe should point there instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# One worker per container; scale by replicas rather than by processes,
# so the platform's own metrics reflect real capacity.
CMD ["uvicorn", "ledgergraph_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
