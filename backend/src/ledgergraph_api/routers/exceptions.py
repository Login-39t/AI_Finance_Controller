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
from ledgergraph_domain.enums import AiValidationStatus
from ledgergraph_reconciliation.policy import Policy

from ..config import get_settings
from ..dto import (
    AiInvestigationDTO,
    CasePacketDTO,
    CasePageDTO,
    case_dto,
    investigation_dto,
    packet_dto,
)
from ..errors import ApiError
from ..store import get_repository, new_audit

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


def _current_run(run_id: str | None):
    repo = get_repository()
    record = repo.get_run(run_id) if run_id else repo.latest_run()
    if record is None or record.result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no completed run; start one at POST /v1/reconciliation-runs",
        )
    return record


@router.get("", response_model=CasePageDTO, summary="Exception queue")
async def list_exceptions(
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
    record = _current_run(run_id)
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

    return CasePageDTO(
        items=[
            case_dto(c, record.run_id, record.ruleset_version, policy) for c in page
        ],
        nextCursor=next_cursor,
        total=len(cases),
    )


@router.get("/{case_id}", response_model=CasePacketDTO, summary="Investigation packet")
async def get_exception(case_id: str) -> CasePacketDTO:
    repo = get_repository()
    case = repo.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case")

    record = repo.latest_run()
    return packet_dto(
        case,
        record.run_id if record else "unknown",
        record.ruleset_version if record else "unknown",
        Policy(),
        investigations=repo.investigations(case_id),
        audit=repo.audit_for(case_id),
    )


@router.post("/{case_id}/investigate", response_model=AiInvestigationDTO,
              summary="Request a grounded AI investigation")
async def request_investigation(case_id: str) -> AiInvestigationDTO:
    """Assemble the packet, call the model, verify the answer.

    A schema violation, an invented citation, or a number the engine did
    not compute all produce a recorded failure rather than a 500 - the
    deterministic finding stands regardless, and a visible refusal is a
    stronger demonstration than an answer that is always available.
    """
    repo = get_repository()
    settings = get_settings()

    case = repo.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case")

    if not settings.ai_enabled:
        raise ApiError(
            "AI_DISABLED",
            "AI investigation is disabled; set AI_ENABLED=true and configure a provider",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    run = repo.latest_run()
    packet = build_packet(case, Redactor(seed=run.run_id if run else "run"))

    try:
        provider = build_provider(
            provider=settings.ai_provider,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            base_url=settings.ai_base_url,
            timeout=settings.ai_timeout_seconds,
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
    repo.add_investigation(case_id, outcome)

    repo.add_audit(new_audit(
        entity_type="exception_case", entity_id=case_id, action="ai_investigated",
        actor_type="ai", actor_name=settings.ai_model,
        detail=(
            f"grounded investigation returned {outcome.status.value} "
            f"after {outcome.attempts} attempt(s); packet {outcome.packet_fingerprint}"
        ),
    ))

    if outcome.status is not AiValidationStatus.VALID:
        # Not an error: a refused answer is a real, displayable outcome.
        # The UI shows why, and the deterministic evidence is unaffected.
        return investigation_dto(len(repo.investigations(case_id)), outcome)

    return investigation_dto(len(repo.investigations(case_id)), outcome)
