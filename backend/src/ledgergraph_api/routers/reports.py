"""Reports and exports.

Two audiences, two shapes, and they are not the same thing:

* `GET /v1/reports/overview` answers "is the close on track" in one
  object, for the controller's dashboard;
* `GET /v1/exports/*` produces CSV a finance team opens in Excel and
  attaches to a close pack.

**Money in an export is a decimal string, not paise.** Everywhere else in
this API money crosses the wire as minor units, precisely so nobody's
JSON parser turns it into a float. An export is the one place that rule
would backfire: a column of `26713994` is not something a controller can
reconcile against a bank statement, and Excel would happily sum it into a
number that means nothing. So exports render `267139.94` - formatted once,
here, from the integer, with no float in the path.

**And the header says so.** Every export carries a comment line naming
the run, the ruleset, and the generation time, because a CSV that
outlives the conversation it was produced in has to say what it is.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from ledgergraph_domain.enums import ExceptionSeverity
from ledgergraph_reconciliation.models import ExceptionCase, RunResult
from ledgergraph_reconciliation.policy import Policy, requires_controller
from pydantic import Field

from ..deps import CanRead
from ..dto import Wire
from ..store import CaseDecision, get_repository

router = APIRouter(tags=["reports"])


def _rupees(minor: int) -> str:
    """Minor units to a plain decimal string. Integer arithmetic only.

    `f"{minor / 100:.2f}"` would be one character shorter and would route
    every amount through a float on the way out - which is the one thing
    this codebase does not do.
    """
    sign = "-" if minor < 0 else ""
    whole, paise = divmod(abs(minor), 100)
    return f"{sign}{whole}.{paise:02d}"


async def _current_run():
    record = await get_repository().latest_run()
    if record is None or record.result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no completed run; start one at POST /v1/reconciliation-runs",
        )
    return record


# --------------------------------------------------------------------------
# The overview
# --------------------------------------------------------------------------

class SeverityCountDTO(Wire):
    severity: str
    count: int
    amountAtRiskMinor: str


class TypeCountDTO(Wire):
    caseType: str
    count: int
    amountAtRiskMinor: str


class DecisionProgressDTO(Wire):
    decided: int
    open: int
    #: Cases a reviewer cannot close on their own.
    awaitingController: int
    decidedValueMinor: str
    openValueMinor: str


class OverviewDTO(Wire):
    runId: str
    rulesetVersion: str
    completedAt: datetime | None
    generatedAt: datetime

    recordsProcessed: int
    groups: int
    autoResolved: int
    pendingReview: int

    #: The headline. Everything else on this object explains it.
    exceptions: int
    exceptionValueMinor: str
    grossProcessedMinor: str

    #: Share of matched value the system cleared without a human. Not a
    #: share of *cases* - one settlement batch is worth a thousand
    #: unmatched refunds, and a case count would flatter the number.
    autoResolutionRate: float
    coverage: float

    bySeverity: list[SeverityCountDTO] = Field(default_factory=list)
    byType: list[TypeCountDTO] = Field(default_factory=list)
    decisions: DecisionProgressDTO
    stageTimingsMs: dict[str, int] = Field(default_factory=dict)


def _severity_order(name: str) -> int:
    order = [s.value for s in ExceptionSeverity]
    return order.index(name) if name in order else len(order)


@router.get("/v1/reports/overview", response_model=OverviewDTO,
            summary="Close-readiness overview for the current run")
async def overview(_: CanRead) -> OverviewDTO:
    repo = get_repository()
    record = await _current_run()
    result: RunResult = record.result
    policy = Policy()
    decisions = await repo.all_decisions()

    cases = result.cases
    exception_value = sum(c.amount_at_risk_minor for c in cases)

    by_severity: dict[str, list[ExceptionCase]] = {}
    by_type: dict[str, list[ExceptionCase]] = {}
    for case in cases:
        by_severity.setdefault(case.severity.value, []).append(case)
        by_type.setdefault(case.case_type.value, []).append(case)

    decided = [c for c in cases if c.case_id in decisions]
    still_open = [c for c in cases if c.case_id not in decisions]
    awaiting_controller = [
        c for c in still_open
        if requires_controller(c.amount_at_risk_minor, policy)
    ]

    summary = result.summary()
    matched_value = sum(g.total_amount_minor for g in result.groups)
    auto_value = sum(g.total_amount_minor for g in result.auto_resolved)

    return OverviewDTO(
        runId=record.run_id,
        rulesetVersion=record.ruleset_version,
        completedAt=record.completed_at,
        generatedAt=datetime.now(UTC),
        recordsProcessed=summary["records_processed"],
        groups=len(result.groups),
        autoResolved=len(result.auto_resolved),
        pendingReview=len(result.pending_review),
        exceptions=len(cases),
        exceptionValueMinor=str(exception_value),
        grossProcessedMinor=str(matched_value),
        # Guarded division: a run over zero matched value is a legitimate
        # state (nothing to reconcile), not a 500.
        autoResolutionRate=round(auto_value / matched_value, 4) if matched_value else 0.0,
        coverage=(
            round(len(result.auto_resolved) / len(result.groups), 4)
            if result.groups else 0.0
        ),
        bySeverity=sorted(
            (
                SeverityCountDTO(
                    severity=name, count=len(group),
                    amountAtRiskMinor=str(sum(c.amount_at_risk_minor for c in group)),
                )
                for name, group in by_severity.items()
            ),
            key=lambda s: _severity_order(s.severity),
        ),
        byType=sorted(
            (
                TypeCountDTO(
                    caseType=name, count=len(group),
                    amountAtRiskMinor=str(sum(c.amount_at_risk_minor for c in group)),
                )
                for name, group in by_type.items()
            ),
            # Sorted by money, not by name: the list is a work queue.
            key=lambda t: -int(t.amountAtRiskMinor),
        ),
        decisions=DecisionProgressDTO(
            decided=len(decided),
            open=len(still_open),
            awaitingController=len(awaiting_controller),
            decidedValueMinor=str(sum(c.amount_at_risk_minor for c in decided)),
            openValueMinor=str(sum(c.amount_at_risk_minor for c in still_open)),
        ),
        stageTimingsMs=result.stage_timings_ms,
    )


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------

def _csv_response(filename: str, header: list[str], rows: list[list[str]],
                  *, run_id: str, ruleset: str) -> StreamingResponse:
    buffer = io.StringIO()

    # A leading comment line, so a file found in a shared drive months
    # later still says which run produced it. Excel shows it as a first
    # row rather than choking, and `csv.reader` callers skip a `#` line.
    buffer.write(
        f"# LedgerGraph export · run {run_id} · ruleset {ruleset} · "
        f"generated {datetime.now(UTC).isoformat(timespec='seconds')} · "
        f"amounts in INR, decimal\n"
    )

    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)

    body = buffer.getvalue()
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Without this the browser downloads it but the length is
            # unknown, so no progress bar on a large close pack.
            "Content-Length": str(len(body.encode("utf-8"))),
        },
    )


@router.get("/v1/exports/exceptions.csv", summary="Every exception, as CSV")
async def export_exceptions(
    _: CanRead,
    severity: str | None = None,
    case_type: str | None = Query(default=None, alias="caseType"),
    undecided_only: bool = Query(default=False, alias="undecidedOnly"),
) -> StreamingResponse:
    """The exception register.

    The filters mirror the queue's, so what a controller exports is what
    they were looking at. An export that silently covers a different set
    than the screen is worse than no export.
    """
    repo = get_repository()
    record = await _current_run()
    policy = Policy()
    decisions = await repo.all_decisions()

    cases = record.result.cases
    if severity:
        cases = [c for c in cases if c.severity.value == severity]
    if case_type:
        cases = [c for c in cases if c.case_type.value == case_type]
    if undecided_only:
        cases = [c for c in cases if c.case_id not in decisions]

    rows = []
    for case in cases:
        decision: CaseDecision | None = decisions.get(case.case_id)
        rows.append([
            case.case_id,
            case.case_type.value,
            case.severity.value,
            _rupees(case.amount_at_risk_minor),
            case.currency,
            case.primary_external_id,
            (case.primary_transaction.source_system.value
             if case.primary_transaction else ""),
            f"{case.confidence:.2f}" if case.confidence is not None else "",
            "yes" if requires_controller(case.amount_at_risk_minor, policy) else "no",
            decision.resolution.value if decision else "open",
            (decision.reason_code.value if decision and decision.reason_code else ""),
            decision.decided_by_name if decision else "",
            decision.decided_by_role.value if decision else "",
            decision.decided_at.isoformat(timespec="seconds") if decision else "",
            (decision.note if decision else "") or "",
            # The hypothesis last: it is the longest field, and a long
            # trailing column is the one that does not wreck the layout.
            case.hypothesis,
        ])

    return _csv_response(
        f"exceptions-{record.run_id}.csv",
        [
            "case_id", "case_type", "severity", "amount_at_risk", "currency",
            "subject_external_id", "source_system", "confidence",
            "requires_controller", "resolution", "reason_code",
            "decided_by", "decided_by_role", "decided_at", "note", "hypothesis",
        ],
        rows,
        run_id=record.run_id, ruleset=record.ruleset_version,
    )


@router.get("/v1/exports/matches.csv", summary="Every match group, as CSV")
async def export_matches(_: CanRead) -> StreamingResponse:
    """One row per group, with the bridge that defends it.

    A reconciliation report that shows only what failed is half a report.
    The auto-resolved rows are the ones an auditor samples.
    """
    record = await _current_run()

    rows = []
    for group in record.result.groups:
        bridge = group.bridge
        rows.append([
            group.group_id,
            group.group_type.value,
            group.matched_by_rule,
            group.tier.value,
            group.status.value,
            f"{group.confidence:.4f}",
            str(len(group.links)),
            _rupees(group.total_amount_minor),
            group.currency,
            " | ".join(sorted(group.transaction_ids)),
            _rupees(bridge.expected_net_minor) if bridge else "",
            _rupees(bridge.observed_net_minor) if bridge else "",
            _rupees(bridge.difference_minor) if bridge else "",
            # Three states, not two: a bridge that balances, one that
            # does not, and a group that has no bridge to speak of.
            # Collapsing the last two into a blank would make the
            # column unable to say "no".
            ("yes" if bridge.balances else "no") if bridge else "n/a",
        ])

    return _csv_response(
        f"matches-{record.run_id}.csv",
        [
            "group_id", "group_type", "matched_by_rule", "tier", "status",
            "confidence", "member_count", "matched_amount", "currency",
            "member_external_ids", "expected_net", "observed_net",
            "difference", "bridge_balances",
        ],
        rows,
        run_id=record.run_id, ruleset=record.ruleset_version,
    )


@router.get("/v1/exports/audit.csv", summary="The audit trail, as CSV")
async def export_audit(_: CanRead) -> StreamingResponse:
    """Append-only, and exportable.

    An audit trail that cannot leave the system is not evidence anyone
    outside the system can use.
    """
    repo = get_repository()
    record = await _current_run()

    events = []
    for case in record.result.cases:
        events.extend(await repo.audit_for(case.case_id))
    events.extend(await repo.audit_for(record.run_id))
    events.sort(key=lambda e: e.created_at)

    rows = [
        [
            event.created_at.isoformat(timespec="seconds"),
            event.entity_type,
            event.entity_id,
            event.action,
            event.actor_type,
            event.actor_name or "",
            event.actor_role or "",
            event.reason_code or "",
            event.ruleset_version or "",
            event.detail,
        ]
        for event in events
    ]

    return _csv_response(
        f"audit-{record.run_id}.csv",
        [
            "occurred_at", "entity_type", "entity_id", "action", "actor_type",
            "actor_name", "actor_role", "reason_code", "ruleset_version", "detail",
        ],
        rows,
        run_id=record.run_id, ruleset=record.ruleset_version,
    )
