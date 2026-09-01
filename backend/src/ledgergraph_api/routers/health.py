"""Liveness and readiness.

Two endpoints, because they answer different questions and a load balancer
needs both:

  /healthz  - is the process alive? No dependencies touched, so a database
              outage never causes the platform to kill a healthy process.
  /readyz   - can it actually serve traffic? Probes the database and
              reports 503 with the reason when it cannot.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from .. import __version__
from ..config import get_settings
from ..db import check_database

router = APIRouter(tags=["ops"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
        "rulesetVersion": settings.ruleset_version,
    }


@router.get("/readyz", summary="Readiness")
async def readyz(response: Response) -> dict[str, Any]:
    settings = get_settings()
    database = await check_database()

    checks = {
        "database": database,
        "ai": {
            "enabled": settings.ai_enabled,
            "model": settings.ai_model if settings.ai_enabled else None,
        },
    }

    ready = database["reachable"]
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if ready else "degraded", "checks": checks}
