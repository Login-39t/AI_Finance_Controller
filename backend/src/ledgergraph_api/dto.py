"""Wire contract, and the mapping from engine models onto it.

Two rules run through everything here.

**Money is a string of minor units.** `"48746770"`, never `487467.70`
and never a JSON number. A JSON number over 2^53 loses precision
silently, and a daily total in paise reaches that sooner than people
expect. Typing it `string` in TypeScript is also what makes
`amount * 1.18` a compile error rather than a rounding bug.

**Field names are camelCase and match `frontend/src/lib/types.ts`
exactly.** That file was hand-written against this contract before the
API existed; matching it means the frontend swaps from fixtures to live
data by deleting a file, not by rewriting components.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ledgergraph_ai.client import InvestigationOutcome
from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import CaseResolution, ExceptionStatus
from ledgergraph_reconciliation.models import (
    Bridge,
    Evidence,
    ExceptionCase,
    MatchGroup,
)
from ledgergraph_reconciliation.policy import Policy, requires_controller
from pydantic import BaseModel, ConfigDict, Field

from .store import AuditEvent, CaseDecision, ImportRecord, RunRecord


class Wire(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# --------------------------------------------------------------------------
# Transactions and evidence
# --------------------------------------------------------------------------

class TransactionDTO(Wire):
    id: str
    entityType: str
    sourceSystem: str
    externalId: str
    parentExternalId: str | None = None
    referenceId: str | None = None
    currency: str
    grossAmountMinor: str
    feeAmountMinor: str
    taxAmountMinor: str
    netAmountMinor: str
    direction: str
    status: str
    eventAt: datetime
    businessDate: str
    tzAssumed: bool
    counterparty: str | None = None
    description: str | None = None
    dataQualityFlags: list[str] = Field(default_factory=list)


class EvidenceDTO(Wire):
    id: str
    ruleCode: str
    evidenceType: str
    statement: str
    computed: dict[str, str]
    passed: bool


class BridgeComponentDTO(Wire):
    label: str
    amountMinor: str
    operation: Literal["base", "subtract", "add"]
    transactionId: str | None = None
    sourceRef: str | None = None


class AmountBridgeDTO(Wire):
    currency: str
    components: list[BridgeComponentDTO]
    expectedNetMinor: str
    observedNetMinor: str
    differenceMinor: str
    toleranceMinor: str
    balances: bool


class GateConditionDTO(Wire):
    key: str
    label: str
    passed: bool
    detail: str


class ScoreComponentsDTO(Wire):
    identifier: float = 0.0
    amount: float = 0.0
    date: float = 0.0
    status: float = 0.0
    counterparty: float = 0.0


class CandidateDTO(Wire):
    id: str
    candidateTransaction: TransactionDTO
    score: float
    scoreComponents: ScoreComponentsDTO
    rank: int
    accepted: bool
    rejectionReason: str | None = None
    marginToRunnerUp: float | None = None


class HypothesisDTO(Wire):
    statement: str
    evidenceIds: list[str]
    likelihood: str


class AiInvestigationDTO(Wire):
    id: str
    modelVersion: str
    promptVersion: str
    validationStatus: str
    validationErrors: list[str]
    classification: str | None = None
    hypotheses: list[HypothesisDTO] = Field(default_factory=list)
    recommendedAction: str | None = None
    requiresHumanApproval: bool | None = None
    confidence: float | None = None
    uncertainties: list[str] = Field(default_factory=list)
    createdAt: datetime


class AuditEventDTO(Wire):
    id: str
    action: str
    actorType: str
    actorName: str | None = None
    actorRole: str | None = None
    reasonCode: str | None = None
    detail: str
    rulesetVersion: str | None = None
    createdAt: datetime


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------

class ExceptionCaseDTO(Wire):
    id: str
    runId: str
    caseType: str
    severity: str
    status: str
    amountAtRiskMinor: str
    currency: str
    confidence: float | None = None
    hypothesis: str | None = None
    recommendation: str | None = None
    assignedTo: str | None = None
    openedAt: datetime
    primaryExternalId: str
    primarySourceSystem: str
    rulesetVersion: str
    requiresControllerApproval: bool
    resolution: str | None = None
    reasonCode: str | None = None
    decisionNote: str | None = None
    decidedBy: str | None = None
    decidedByRole: str | None = None
    decidedAt: datetime | None = None


class CaseMemberDTO(Wire):
    role: str
    transaction: TransactionDTO


class CasePacketDTO(ExceptionCaseDTO):
    transactions: list[CaseMemberDTO] = Field(default_factory=list)
    bridge: AmountBridgeDTO | None = None
    evidence: list[EvidenceDTO] = Field(default_factory=list)
    candidates: list[CandidateDTO] = Field(default_factory=list)
    gate: list[GateConditionDTO] = Field(default_factory=list)
    aiInvestigations: list[AiInvestigationDTO] = Field(default_factory=list)
    audit: list[AuditEventDTO] = Field(default_factory=list)


class CasePageDTO(Wire):
    items: list[ExceptionCaseDTO]
    nextCursor: str | None = None
    total: int


# --------------------------------------------------------------------------
# Imports and runs
# --------------------------------------------------------------------------

class RejectionDTO(Wire):
    rowNumber: int
    columnName: str | None = None
    rawValue: str | None = None
    errorCode: str
    errorMessage: str


class ImportDTO(Wire):
    id: str
    dataset: str
    filename: str
    status: str
    rowsTotal: int
    rowsAccepted: int
    rowsRejected: int
    createdAt: datetime
    completedAt: datetime | None = None
    error: str | None = None


class ImportDetailDTO(ImportDTO):
    rejections: list[RejectionDTO] = Field(default_factory=list)


class RunMetricsDTO(Wire):
    recordsProcessed: int
    groups: int
    autoResolved: int
    pendingReview: int
    exceptions: int
    grossProcessedMinor: str
    unresolvedValueMinor: str
    stageTimingsMs: dict[str, int] = Field(default_factory=dict)


class RunDTO(Wire):
    id: str
    status: str
    rulesetVersion: str
    currentStage: str | None = None
    progressPct: int
    createdAt: datetime
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    error: str | None = None
    metrics: RunMetricsDTO | None = None


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------

def transaction_dto(txn: CanonicalTransaction) -> TransactionDTO:
    return TransactionDTO(
        id=txn.external_id_norm,
        entityType=txn.entity_type.value,
        sourceSystem=txn.source_system.value,
        externalId=txn.external_id,
        parentExternalId=txn.parent_external_id,
        referenceId=txn.reference_id,
        currency=txn.currency,
        grossAmountMinor=str(txn.gross_amount_minor),
        feeAmountMinor=str(txn.fee_amount_minor),
        taxAmountMinor=str(txn.tax_amount_minor),
        netAmountMinor=str(txn.net_amount_minor),
        direction=txn.direction.value,
        status=txn.status.value,
        eventAt=txn.event_at,
        businessDate=txn.business_date.isoformat(),
        tzAssumed=txn.tz_assumed,
        counterparty=txn.counterparty,
        description=txn.description,
        dataQualityFlags=list(txn.data_quality_flags),
    )


def evidence_dto(case_id: str, index: int, ev: Evidence) -> EvidenceDTO:
    # Same id scheme the AI packet uses, so a citation shown in the UI and
    # a citation the verifier checked are the same string.
    return EvidenceDTO(
        id=f"{case_id}:ev{index}",
        ruleCode=ev.rule_code,
        evidenceType=ev.evidence_type,
        statement=ev.statement,
        computed={k: str(v) for k, v in ev.computed.items()},
        passed=ev.passed,
    )


def bridge_dto(bridge: Bridge) -> AmountBridgeDTO:
    return AmountBridgeDTO(
        currency=bridge.currency,
        components=[
            BridgeComponentDTO(
                label=c.label,
                amountMinor=str(c.amount_minor),
                operation=c.operation,
                sourceRef=c.source_ref,
            )
            for c in bridge.components
        ],
        expectedNetMinor=str(bridge.expected_net_minor),
        observedNetMinor=str(bridge.observed_net_minor),
        differenceMinor=str(bridge.difference_minor),
        toleranceMinor=str(bridge.tolerance_minor),
        balances=bridge.balances,
    )


def case_dto(
    case: ExceptionCase, run_id: str, ruleset: str, policy: Policy,
    decision: CaseDecision | None = None,
) -> ExceptionCaseDTO:
    return ExceptionCaseDTO(
        id=case.case_id,
        runId=run_id,
        caseType=case.case_type.value,
        severity=case.severity.value,
        # The engine opens a case; a person closes it. `unresolved` is a
        # first-class outcome rather than a failure - abstention is what
        # keeps the false-clear rate at zero.
        status=_case_status(case, decision),
        amountAtRiskMinor=str(case.amount_at_risk_minor),
        currency=case.currency,
        confidence=case.confidence,
        hypothesis=case.hypothesis or None,
        recommendation=case.recommendation or None,
        assignedTo=None,
        resolution=decision.resolution.value if decision else None,
        reasonCode=(
            decision.reason_code.value if decision and decision.reason_code else None
        ),
        decisionNote=(decision.note or None) if decision else None,
        decidedBy=decision.decided_by_name if decision else None,
        decidedByRole=decision.decided_by_role.value if decision else None,
        decidedAt=decision.decided_at if decision else None,
        openedAt=datetime.now(tz=None).astimezone(),
        primaryExternalId=case.primary_external_id,
        primarySourceSystem=(
            case.primary_transaction.source_system.value
            if case.primary_transaction else "gateway_payments"
        ),
        rulesetVersion=ruleset,
        requiresControllerApproval=requires_controller(case.amount_at_risk_minor, policy),
    )


def _case_status(case: ExceptionCase, decision: CaseDecision | None) -> str:
    if decision is not None:
        if decision.resolution is CaseResolution.DISMISSED:
            return ExceptionStatus.DISMISSED.value
        return ExceptionStatus.RESOLVED.value
    if case.group and not case.group.auto_resolved:
        return ExceptionStatus.UNRESOLVED.value
    return ExceptionStatus.OPEN.value


def _role_for(group: MatchGroup | None, txn: CanonicalTransaction) -> str:
    if group is not None:
        for link in group.links:
            if link.transaction.external_id_norm == txn.external_id_norm:
                return link.role.value
    return "subject"


def packet_dto(
    case: ExceptionCase, run_id: str, ruleset: str, policy: Policy,
    *, investigations: list[InvestigationOutcome], audit: list[AuditEvent],
    decision: CaseDecision | None = None,
) -> CasePacketDTO:
    base = case_dto(case, run_id, ruleset, policy, decision)

    members: list[CaseMemberDTO] = []
    seen: set[str] = set()
    for txn in case.transactions:
        if txn.external_id_norm in seen:
            continue
        seen.add(txn.external_id_norm)
        members.append(CaseMemberDTO(
            role=_role_for(case.group, txn), transaction=transaction_dto(txn)
        ))

    return CasePacketDTO(
        **base.model_dump(),
        transactions=members,
        bridge=bridge_dto(case.group.bridge) if case.group and case.group.bridge else None,
        evidence=[evidence_dto(case.case_id, i, e)
                  for i, e in enumerate(case.evidence, start=1)],
        candidates=[],
        gate=[
            GateConditionDTO(key=c.key, label=c.label, passed=c.passed, detail=c.detail)
            for c in (case.group.gate if case.group else [])
        ],
        aiInvestigations=[investigation_dto(i, o) for i, o in enumerate(investigations, 1)],
        audit=[audit_dto(e) for e in audit],
    )


def investigation_dto(index: int, outcome: InvestigationOutcome) -> AiInvestigationDTO:
    inv = outcome.investigation
    return AiInvestigationDTO(
        id=f"ai_{index}",
        modelVersion=outcome.model_version,
        promptVersion=outcome.prompt_version,
        validationStatus=outcome.status.value,
        validationErrors=list(outcome.errors),
        classification=inv.classification.value if inv else None,
        hypotheses=[
            HypothesisDTO(
                statement=h.statement, evidenceIds=h.evidence_ids, likelihood=h.likelihood
            )
            for h in (inv.hypotheses if inv else [])
        ],
        recommendedAction=inv.recommended_action if inv else None,
        requiresHumanApproval=inv.requires_human_approval if inv else None,
        confidence=inv.confidence if inv else None,
        uncertainties=list(inv.uncertainties) if inv else [],
        createdAt=datetime.now(tz=None).astimezone(),
    )


def audit_dto(event: AuditEvent) -> AuditEventDTO:
    return AuditEventDTO(
        id=event.event_id,
        action=event.action,
        actorType=event.actor_type,
        actorName=event.actor_name,
        actorRole=event.actor_role,
        reasonCode=event.reason_code,
        detail=event.detail,
        rulesetVersion=event.ruleset_version,
        createdAt=event.created_at,
    )


def import_dto(record: ImportRecord, *, detail: bool = False) -> ImportDTO:
    payload = dict(
        id=record.import_id, dataset=record.dataset, filename=record.filename,
        status=record.status.value, rowsTotal=record.rows_total,
        rowsAccepted=record.rows_accepted, rowsRejected=record.rows_rejected,
        createdAt=record.created_at, completedAt=record.completed_at, error=record.error,
    )
    if not detail:
        return ImportDTO(**payload)
    return ImportDetailDTO(
        **payload,
        rejections=[
            RejectionDTO(
                rowNumber=r["row_number"], columnName=r.get("column_name"),
                rawValue=r.get("raw_value"), errorCode=r["error_code"],
                errorMessage=r["error_message"],
            )
            for r in record.rejections
        ],
    )


def run_dto(record: RunRecord) -> RunDTO:
    metrics = None
    if record.result is not None:
        summary = record.result.summary()
        gross = sum(
            link.transaction.gross_amount_minor
            for g in record.result.groups for link in g.links
        )
        unresolved = sum(c.amount_at_risk_minor for c in record.result.cases)
        metrics = RunMetricsDTO(
            recordsProcessed=summary["records_processed"],
            groups=summary["groups"],
            autoResolved=summary["auto_resolved"],
            pendingReview=summary["pending_review"],
            exceptions=summary["exceptions"],
            grossProcessedMinor=str(gross),
            unresolvedValueMinor=str(unresolved),
            stageTimingsMs=dict(record.result.stage_timings_ms),
        )

    return RunDTO(
        id=record.run_id, status=record.status.value,
        rulesetVersion=record.ruleset_version, currentStage=record.current_stage,
        progressPct=record.progress_pct, createdAt=record.created_at,
        startedAt=record.started_at, completedAt=record.completed_at,
        error=record.error, metrics=metrics,
    )
