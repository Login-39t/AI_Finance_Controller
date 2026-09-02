"""The exception queue and case detail.

`GET /v1/exceptions/{id}` is deliberately a fat endpoint. It returns the
whole packet - members, bridge, evidence, gate, prior investigations,
audit - in one response, and the same assembler feeds the model prompt.
Six requests to render one page would be slower, and worse, it would make
packet assembly a second code path that can drift from what the human
sees. One assembler is what makes "the model and the analyst saw the same
evidence" true rather than intended.
"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, HTTPException, Query, status
from ledgergraph_ai import Redactor, build_packet, investigate
from ledgergraph_ai.client import build_provider
from ledgergraph_domain.enums import (
    AiValidationStatus,
    CaseResolution,
    ReasonCode,
    UserRole,
)
from ledgergraph_reconciliation.policy import Policy, requires_controller
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import CanDecide, CanRead
from ..dto import (
    AiInvestigationDTO,
    CasePacketDTO,
    CasePageDTO,
    case_dto,
    investigation_dto,
    packet_dto,
)
from ..errors import ApiError
from ..store import CaseDecision, get_repository, new_audit

router = APIRouter(prefix="/v1/exceptions", tags=["exceptions"])

MAX_LIMIT = 200


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(cursor.encode()))["o"])
    except Exception:  # noqa: BLE001 - a bad cursor is a client error
        raise ApiError(
            "INVALID_CURSOR", "cursor is malformed",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from None


async def _current_run(run_id: str | None):
    repo = get_repository()
    record = await repo.get_run(run_id) if run_id else await repo.latest_run()
    if record is None or record.result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no completed run; start one at POST /v1/reconciliation-runs",
        )
    return record


@router.get("", response_model=CasePageDTO, summary="Exception queue")
async def list_exceptions(
    _: CanRead,
    run_id: str | None = Query(default=None, alias="runId"),
    case_type: str | None = Query(default=None, alias="caseType"),
    severity: str | None = None,
    min_amount_minor: int | None = Query(default=None, alias="minAmountMinor"),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
) -> CasePageDTO:
    """Sorted by amount at risk, descending.

    The sort is applied by the engine and preserved here rather than being
    a client concern: it is the queue's contract with the analyst, and a
    default that put cheap problems first would waste the scarcest thing
    in the system, which is attention.
    """
    record = await _current_run(run_id)
    policy = Policy()

    cases = record.result.cases
    if case_type:
        cases = [c for c in cases if c.case_type.value == case_type]
    if severity:
        cases = [c for c in cases if c.severity.value == severity]
    if min_amount_minor is not None:
        cases = [c for c in cases if c.amount_at_risk_minor >= min_amount_minor]

    offset = _decode_cursor(cursor)
    page = cases[offset: offset + limit]
    next_cursor = (
        _encode_cursor(offset + limit) if offset + limit < len(cases) else None
    )

    decisions = await get_repository().all_decisions()
    return CasePageDTO(
        items=[
            case_dto(c, record.run_id, record.ruleset_version, policy,
                     decisions.get(c.case_id))
            for c in page
        ],
        nextCursor=next_cursor,
        total=len(cases),
    )


@router.get("/{case_id}", response_model=CasePacketDTO, summary="Investigation packet")
async def get_exception(case_id: str, _: CanRead) -> CasePacketDTO:
    repo = get_repository()
    case = await repo.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case")

    record = await repo.latest_run()
    return packet_dto(
        case,
        record.run_id if record else "unknown",
        record.ruleset_version if record else "unknown",
        Policy(),
        investigations=await repo.investigations(case_id),
        audit=await repo.audit_for(case_id),
        decision=await repo.get_decision(case_id),
    )


@router.post("/{case_id}/investigate", response_model=AiInvestigationDTO,
              summary="Request a grounded AI investigation")
async def request_investigation(case_id: str, user: CanRead) -> AiInvestigationDTO:
    """Assemble the packet, call the model, verify the answer.

    A schema violation, an invented citation, or a number the engine did
    not compute all produce a recorded failure rather than a 500 - the
    deterministic finding stands regardless, and a visible refusal is a
    stronger demonstration than an answer that is always available.
    """
    repo = get_repository()
    settings = get_settings()

    case = await repo.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case")

    if not settings.ai_enabled:
        raise ApiError(
            "AI_DISABLED",
            "AI investigation is disabled; set AI_ENABLED=true and configure a provider",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    run = await repo.latest_run()
    packet = build_packet(case, Redactor(seed=run.run_id if run else "run"))

    try:
        provider = build_provider(
            provider=settings.ai_provider,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            base_url=settings.ai_base_url,
            timeout=settings.ai_timeout_seconds,
            region=settings.aws_region,
        )
    except ValueError as exc:
        raise ApiError(
            "AI_MISCONFIGURED", str(exc),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    outcome = investigate(
        packet, provider,
        model_version=settings.ai_model,
        max_retries=settings.ai_max_retries,
    )
    await repo.add_investigation(case_id, outcome)

    await repo.add_audit(new_audit(
        entity_type="exception_case", entity_id=case_id, action="ai_investigated",
        actor_type="ai", actor_name=settings.ai_model,
        actor_role=user.role.value,
        detail=(
            f"grounded investigation returned {outcome.status.value} "
            f"after {outcome.attempts} attempt(s); packet {outcome.packet_fingerprint}"
        ),
    ))

    if outcome.status is not AiValidationStatus.VALID:
        # Not an error: a refused answer is a real, displayable outcome.
        # The UI shows why, and the deterministic evidence is unaffected.
        return investigation_dto(len(await repo.investigations(case_id)), outcome)

    return investigation_dto(len(await repo.investigations(case_id)), outcome)


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------

class DecisionRequest(BaseModel):
    resolution: CaseResolution
    reasonCode: ReasonCode | None = None
    note: str = Field(default="", max_length=2000)


@router.post("/{case_id}/decision", response_model=CasePacketDTO,
              summary="Approve, reject, override, or dismiss a case")
async def decide(case_id: str, body: DecisionRequest, user: CanDecide) -> CasePacketDTO:
    """Record a human verdict, with an audit event written beside it.

    Three checks, and each one exists because the others do not cover it:

    1. **role** - handled by the `CanDecide` dependency; an analyst reads
       and investigates but does not decide.
    2. **amount** - a reviewer may not clear a case above the material
       threshold. This cannot live on the route, because it depends on
       the case rather than the caller (PRD story D2).
    3. **reason code** - mandatory on an override, which is the decision
       that contradicts the engine and therefore the one that most needs
       a defensible record (PRD story D1, mirrored by a CHECK constraint
       in `db/schema.sql`).

    A decision is not idempotent and not silently replaceable: a second
    decision on an already-decided case is a 409 rather than an
    overwrite, because the audit trail is the product here and quietly
    losing the first verdict would defeat it.
    """
    repo = get_repository()
    case = await repo.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case")

    existing = await repo.get_decision(case_id)
    if existing is not None:
        raise ApiError(
            "ALREADY_DECIDED",
            (
                f"this case was already {existing.resolution.value} by "
                f"{existing.decided_by_name}; reopen it before deciding again"
            ),
            status_code=status.HTTP_409_CONFLICT,
        )

    policy = Policy()
    material = requires_controller(case.amount_at_risk_minor, policy)
    if material and user.role not in (UserRole.CONTROLLER, UserRole.ADMIN):
        raise ApiError(
            "CONTROLLER_APPROVAL_REQUIRED",
            (
                f"{_rupees(case.amount_at_risk_minor)} is above the "
                f"{_rupees(policy.review_required_above_minor)} threshold; "
                f"only a controller may decide this case"
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if body.resolution is CaseResolution.AUTO_RESOLVED:
        # The engine owns this value. A human recording it by hand would
        # make the auto-resolution precision metric a lie.
        raise ApiError(
            "NOT_A_HUMAN_RESOLUTION",
            "auto_resolved is produced by the gate, not by a person",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if body.resolution is CaseResolution.OVERRIDDEN and body.reasonCode is None:
        raise ApiError(
            "REASON_CODE_REQUIRED",
            "an override must carry a reason code from the controlled list",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    decision = CaseDecision(
        case_id=case_id, resolution=body.resolution, reason_code=body.reasonCode,
        note=body.note.strip(), decided_by=user.user_id,
        decided_by_name=user.full_name, decided_by_role=user.role,
    )
    await repo.record_decision(decision)
    await repo.add_audit(new_audit(
        entity_type="exception_case", entity_id=case_id,
        action=body.resolution.value, actor_type="user",
        actor_name=user.full_name, actor_role=user.role.value,
        reason_code=body.reasonCode.value if body.reasonCode else None,
        detail=(
            decision.note
            or f"{body.resolution.value} on {_rupees(case.amount_at_risk_minor)} at risk"
        ),
        ruleset_version=get_settings().ruleset_version,
    ))

    record = await repo.latest_run()
    return packet_dto(
        case,
        record.run_id if record else "unknown",
        record.ruleset_version if record else "unknown",
        policy,
        investigations=await repo.investigations(case_id),
        audit=await repo.audit_for(case_id),
        decision=decision,
    )


def _rupees(minor: int) -> str:
    return f"Rs {minor / 100:,.2f}"
