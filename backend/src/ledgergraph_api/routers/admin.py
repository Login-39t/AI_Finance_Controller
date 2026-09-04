"""Maintenance actions for a demo deployment.

Only one, and a blunt one: empty the reconciliation working set so a
recording or a walkthrough can start from nothing. It is guarded twice -
admin only, and refused outright under `ENVIRONMENT=production` - because
"delete every import and run" is exactly the button you never want within
reach of a real ledger. On the staging demo it is a convenience; on
production it does not exist.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from ..config import get_settings
from ..deps import CanAdmin
from ..errors import ApiError
from ..store import get_repository

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/reset", summary="Wipe imports and runs (admin, non-production)")
async def reset_reconciliation(actor: CanAdmin) -> dict[str, object]:
    """Delete every import, run, and derived record. Keeps accounts.

    Returns a small confirmation rather than 204, so a caller (or a curl in
    a demo script) sees plainly that it happened and who did it.
    """
    settings = get_settings()
    if settings.environment == "production":
        raise ApiError(
            "RESET_FORBIDDEN_IN_PRODUCTION",
            "the reconciliation reset is disabled under ENVIRONMENT=production",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    await get_repository().reset_reconciliation_data()
    return {
        "reset": True,
        "by": actor.email,
        "kept": ["accounts", "roles", "policies"],
        "cleared": ["imports", "runs", "cases", "investigations", "audit trail"],
    }
