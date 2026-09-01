"""The auto-resolution gate.

This is the smallest file in the engine and the one the submission's
central claim rests on. Six conditions, all of which must hold. Any single
failure routes the group to a human.

Two properties matter more than the thresholds themselves:

**It is deterministic.** It reads engine-computed values only. No model
output reaches it - not the AI's classification, and specifically not the
AI's confidence. A model that is certain and wrong changes nothing here.

**It records its reasoning.** Every condition is returned with the value
it was evaluated against, so `gate_result` answers "why was this not
cleared" without anyone reading code. That is what makes the abstention
auditable rather than merely correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgergraph_domain.enums import ExceptionType, GroupStatus, RuleTier

from .models import GateCondition, MatchGroup


@dataclass(frozen=True, slots=True)
class Policy:
    """Thresholds. Data, not code - PRD section 5.3.

    Changing one is a config change with an audit trail, which is why
    these live in a `policies` table rather than as constants.
    """

    version: int = 1
    auto_resolve_min_confidence: float = 0.95
    auto_resolve_max_minor: int = 5_000_000          # Rs 50,000
    review_required_above_minor: int = 25_000_000    # Rs 2,50,000
    candidate_margin: float = 0.05
    settlement_window_days: int = 3
    amount_tolerance_minor: int = 100                # Rs 1.00
    max_candidates_per_record: int = 20
    never_auto_resolve: frozenset[ExceptionType] = field(
        default_factory=lambda: frozenset({
            ExceptionType.DUPLICATE,
            ExceptionType.MISSING_BANK_CREDIT,
            ExceptionType.AMOUNT_MISMATCH,
        })
    )


def evaluate_gate(
    group: MatchGroup,
    policy: Policy,
    *,
    case_type: ExceptionType | None = None,
    margin_to_runner_up: float | None = None,
    amount_at_risk_minor: int = 0,
) -> list[GateCondition]:
    """Evaluate all six conditions and return them with their values.

    Every condition is evaluated even after one has already failed. Short
    circuiting would be marginally faster and would leave the audit record
    unable to answer "what else was wrong with this".
    """
    conditions: list[GateCondition] = []

    # 1. Confidence floor.
    conditions.append(GateCondition(
        key="confidence",
        label=f"Confidence at or above {policy.auto_resolve_min_confidence:.2f}",
        passed=group.confidence >= policy.auto_resolve_min_confidence,
        detail=f"{group.confidence:.2f}",
    ))

    # 2. Deterministic tier. A scored match may be right and still is not
    #    a basis for clearing without review.
    conditions.append(GateCondition(
        key="tier",
        label="Matched by a deterministic rule",
        passed=group.tier is RuleTier.DETERMINISTIC,
        detail=f"{group.tier.value}, {group.matched_by_rule}",
    ))

    # 3. Material exposure - amount *at risk*, not the group's total value.
    #
    # PRD 5.3 specifies `amount_at_risk_minor <= auto_resolve_max_minor`,
    # and the distinction decides real cases. A settlement batch that
    # reconciles to the paise has zero exposure however large it is;
    # gating on total value instead would hold every large-but-perfect
    # payout for manual sign-off while a small batch with a hole the size
    # of itself sailed through. Materiality of *value* is a separate
    # control and lives in `review_required_above_minor`, which decides
    # who may approve rather than whether the system may clear.
    conditions.append(GateCondition(
        key="amount",
        label=f"Exposure at or below {_rupees(policy.auto_resolve_max_minor)}",
        passed=amount_at_risk_minor <= policy.auto_resolve_max_minor,
        detail=_rupees(amount_at_risk_minor),
    ))

    # 4. Block list. Some exception types are never safe to clear
    #    automatically no matter how well the numbers line up.
    blocked = case_type in policy.never_auto_resolve if case_type else False
    has_dispute = any(
        link.transaction.entity_type.value == "dispute" for link in group.links
    )
    conditions.append(GateCondition(
        key="type",
        label="Case type is not on the block list",
        passed=not blocked and not has_dispute,
        detail=(
            f"{case_type.value} is blocked" if blocked
            else "a dispute is involved" if has_dispute
            else (case_type.value if case_type else "no exception type")
        ),
    ))

    # 5. Unambiguity. A near-tie between candidates means the evidence
    #    does not identify one answer, which is the abstention case.
    if margin_to_runner_up is None:
        margin_ok, margin_detail = True, "no competing candidate"
    else:
        # Strictly greater, not `>=`. The blueprint requires no competing
        # candidate *within* the margin, so a runner-up sitting exactly on
        # the threshold is inside it. The boundary is worth being explicit
        # about because it decides a real case in the demo dataset: two
        # bank credits separated by exactly 0.05 are not distinguishable
        # on evidence, and clearing one of them would be a guess.
        margin_ok = margin_to_runner_up > policy.candidate_margin
        margin_detail = f"margin {margin_to_runner_up:.2f}"
    conditions.append(GateCondition(
        key="margin",
        label=f"Runner-up is more than {policy.candidate_margin:.2f} behind",
        passed=margin_ok,
        detail=margin_detail,
    ))

    # 6. Data quality. A flagged member record means something about the
    #    input is already known to be unreliable.
    flagged = sorted({
        flag
        for link in group.links
        for flag in link.transaction.data_quality_flags
    })
    conditions.append(GateCondition(
        key="quality",
        label="No open data-quality flag on any member",
        passed=not flagged,
        detail=", ".join(flagged) if flagged else "clean",
    ))

    return conditions


def apply_gate(
    group: MatchGroup,
    policy: Policy,
    *,
    case_type: ExceptionType | None = None,
    margin_to_runner_up: float | None = None,
    amount_at_risk_minor: int = 0,
) -> MatchGroup:
    """Evaluate the gate and set the group's status accordingly.

    A group with no passing evidence can never be auto-resolved, whatever
    the gate says - the same invariant the database enforces with the
    require_evidence constraint trigger. "Resolved because a rule said so,
    with no record of what the rule compared" is exactly the outcome this
    system exists to make impossible.
    """
    group.gate = evaluate_gate(
        group, policy,
        case_type=case_type,
        margin_to_runner_up=margin_to_runner_up,
        amount_at_risk_minor=amount_at_risk_minor,
    )

    passed_all = all(c.passed for c in group.gate)
    if passed_all and group.has_passing_evidence():
        group.status = GroupStatus.AUTO_RESOLVED
    else:
        group.status = GroupStatus.PENDING_REVIEW

    return group


def requires_controller(amount_minor: int, policy: Policy) -> bool:
    """Above the material threshold only a controller may approve.

    Checked in the service layer as well as here, because it depends on
    the case's amount rather than on the caller's role alone.
    """
    return amount_minor > policy.review_required_above_minor


def _rupees(minor: int) -> str:
    return f"Rs {minor / 100:,.2f}"
