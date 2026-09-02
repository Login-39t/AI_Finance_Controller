"""The match groups, browsable.

The exception queue answers "what is wrong". This answers "what did the
engine decide, and why" — including everything it got right, which is the
part an auditor samples and the part a rule change silently breaks.

A reconciliation tool that only exposes its failures cannot be checked.
If the only way to see an auto-resolved group is to read a CSV, then in
practice nobody ever looks at one, and the auto-resolution precision
number is taken on trust rather than spot-checked.
"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, HTTPException, Query, status
from ledgergraph_reconciliation.policy import Policy
from pydantic import Field

from ..deps import CanRead
from ..dto import (
    AmountBridgeDTO,
    CaseMemberDTO,
    EvidenceDTO,
    GateConditionDTO,
    Wire,
    bridge_dto,
    evidence_dto,
    transaction_dto,
)
from ..errors import ApiError
from ..store import get_repository

router = APIRouter(prefix="/v1/match-groups", tags=["matches"])

MAX_LIMIT = 200


class MatchGroupDTO(Wire):
    id: str
    groupType: str
    matchedByRule: str
    tier: str
    status: str
    confidence: float
    memberCount: int
    matchedAmountMinor: str
    currency: str
    explanation: str | None = None
    bridgeBalances: bool | None = None
    #: How many of the six gate conditions held. The denominator is fixed,
    #: so `4 of 6` is readable without unpacking the whole list.
    gatePassed: int = 0
    gateTotal: int = 0


class MatchGroupDetailDTO(MatchGroupDTO):
    transactions: list[CaseMemberDTO] = Field(default_factory=list)
    bridge: AmountBridgeDTO | None = None
    evidence: list[EvidenceDTO] = Field(default_factory=list)
    gate: list[GateConditionDTO] = Field(default_factory=list)
    confidenceComponents: dict[str, float] = Field(default_factory=dict)


class MatchGroupPageDTO(Wire):
    items: list[MatchGroupDTO]
    nextCursor: str | None = None
    total: int
    #: Counts across the *whole* filtered set, not the current page, so
    #: the tabs above a paginated list do not change as you page.
    statusCounts: dict[str, int] = Field(default_factory=dict)


def _encode(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _decode(cursor: str | None) -> int:
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


def _summary(group) -> MatchGroupDTO:
    return MatchGroupDTO(
        id=group.group_id,
        groupType=group.group_type.value,
        matchedByRule=group.matched_by_rule,
        tier=group.tier.value,
        status=group.status.value,
        confidence=round(group.confidence, 4),
        memberCount=len(group.links),
        matchedAmountMinor=str(group.total_amount_minor),
        currency=group.currency,
        explanation=group.explanation or None,
        bridgeBalances=group.bridge.balances if group.bridge else None,
        gatePassed=sum(1 for c in group.gate if c.passed),
        gateTotal=len(group.gate),
    )


@router.get("", response_model=MatchGroupPageDTO, summary="Browse match groups")
async def list_groups(
    _: CanRead,
    run_id: str | None = Query(default=None, alias="runId"),
    group_status: str | None = Query(default=None, alias="status"),
    rule: str | None = None,
    min_amount_minor: int | None = Query(default=None, alias="minAmountMinor"),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
) -> MatchGroupPageDTO:
    """Sorted by matched value, descending — same principle as the queue.

    The status counts are computed over the filtered set before paging,
    because a tab bar whose numbers change as you page through is worse
    than no tab bar.
    """
    record = _current_run(run_id)
    groups = list(record.result.groups)

    if rule:
        groups = [g for g in groups if g.matched_by_rule == rule]
    if min_amount_minor is not None:
        groups = [g for g in groups if g.total_amount_minor >= min_amount_minor]

    counts: dict[str, int] = {}
    for group in groups:
        counts[group.status.value] = counts.get(group.status.value, 0) + 1

    if group_status:
        groups = [g for g in groups if g.status.value == group_status]

    groups.sort(key=lambda g: g.total_amount_minor, reverse=True)

    offset = _decode(cursor)
    page = groups[offset: offset + limit]

    return MatchGroupPageDTO(
        items=[_summary(g) for g in page],
        nextCursor=_encode(offset + limit) if offset + limit < len(groups) else None,
        total=len(groups),
        statusCounts=counts,
    )


@router.get("/{group_id}", response_model=MatchGroupDetailDTO,
            summary="One group, with its evidence and bridge")
async def get_group(group_id: str, _: CanRead) -> MatchGroupDetailDTO:
    repo = get_repository()
    group = repo.get_group(group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such group")

    # Unused here beyond documenting that thresholds are policy data, but
    # kept explicit so a future filter on materiality has one source.
    _ = Policy()

    members: list[CaseMemberDTO] = []
    seen: set[str] = set()
    for link in group.links:
        txn = link.transaction
        if txn.external_id_norm in seen:
            continue
        seen.add(txn.external_id_norm)
        members.append(
            CaseMemberDTO(role=link.role.value, transaction=transaction_dto(txn))
        )

    return MatchGroupDetailDTO(
        **_summary(group).model_dump(),
        transactions=members,
        bridge=bridge_dto(group.bridge) if group.bridge else None,
        evidence=[
            evidence_dto(group.group_id, i, e)
            for i, e in enumerate(group.evidence, start=1)
        ],
        gate=[
            GateConditionDTO(key=c.key, label=c.label, passed=c.passed, detail=c.detail)
            for c in group.gate
        ],
        confidenceComponents={
            k: round(v, 4) for k, v in group.confidence_components.items()
        },
    )
