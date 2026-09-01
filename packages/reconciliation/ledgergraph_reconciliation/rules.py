"""Deterministic matching rules R1-R5, plus the scored R6.

Rules run in order and the first match wins. Ordering is not arbitrary:
each rule is strictly weaker evidence than the one before it, so a record
matched by R1 must never be reconsidered by R6. `TransactionIndex.consume`
enforces that, the same way the partial unique index does in the database.

Every rule emits an `Evidence` row carrying the values it compared, not a
summary of them. A group with no passing evidence cannot be resolved.

    R1  payment      <- settlement line     exact parent id
    R2  batch        <- bank credit         exact reference + exact net
    R3  batch        vs its lines           arithmetic integrity
    R4  invoice      <- payment             shared order id + amount
    R5  ledger       <- batch               reference + balanced journal
    R6  batch        <- bank credit         amount + date window, scored
"""

from __future__ import annotations

from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import (
    EntityType,
    GroupType,
    LinkRole,
    RuleTier,
    TxnStatus,
)

from .bridge import build_ledger_bridge, build_settlement_bridge, fee_matches_schedule
from .index import TransactionIndex
from .models import Evidence, Link, MatchGroup
from .policy import Policy
from .scoring import margin_between, score_candidate

SETTLED_STATUSES = {TxnStatus.SETTLED, TxnStatus.POSTED}


def _money(minor: int) -> str:
    return str(minor)


# --------------------------------------------------------------------------
# R1 - payment to settlement line
# --------------------------------------------------------------------------

def match_r1_payment_to_line(
    index: TransactionIndex,
) -> dict[str, CanonicalTransaction]:
    """Link each settlement line to the payment it names.

    Returns a map of line id -> payment, consumed by the batch grouping
    rather than producing standalone groups: a payment/line pair on its
    own is not a reconciliation, it is one edge of the settlement chain.
    """
    linked: dict[str, CanonicalTransaction] = {}

    for line in index.of_type(EntityType.SETTLEMENT_LINE):
        payment = index.get(line.parent_external_id)
        if payment is None or payment.entity_type is not EntityType.PAYMENT:
            continue
        if payment.gross_amount_minor != line.gross_amount_minor:
            # The line claims to settle this payment but for a different
            # gross. That is an amount_mismatch, not a match.
            continue
        linked[line.external_id_norm] = payment

    return linked


# --------------------------------------------------------------------------
# R2 / R6 - batch to bank credit
# --------------------------------------------------------------------------

def match_r2_batch_to_bank(
    batch: CanonicalTransaction, index: TransactionIndex
) -> tuple[CanonicalTransaction | None, Evidence]:
    """Exact reference plus exact net. The strongest bank link available."""
    if not batch.reference_id:
        return None, Evidence(
            rule_code="R2",
            evidence_type="exact_reference",
            statement="No settlement reference is present, so no exact bank match is possible.",
            computed={"batch.reference_id": "(absent)"},
            passed=False,
        )

    for bank in index.referencing(batch.reference_id):
        if bank.entity_type is not EntityType.BANK_TRANSACTION:
            continue
        if index.is_consumed(bank):
            continue
        if bank.net_amount_minor != batch.net_amount_minor:
            continue
        return bank, Evidence(
            rule_code="R2",
            evidence_type="exact_reference",
            statement="Bank credit carries the settlement reference and matches the net exactly.",
            computed={
                "batch.reference_id": batch.reference_id,
                "bank.reference_id": bank.reference_id or "",
                "batch.net": _money(batch.net_amount_minor),
                "bank.net": _money(bank.net_amount_minor),
                "difference": "0",
            },
            passed=True,
        )

    return None, Evidence(
        rule_code="R2",
        evidence_type="exact_reference",
        statement="No bank credit carries this settlement reference at the expected net.",
        computed={
            "batch.reference_id": batch.reference_id,
            "batch.net": _money(batch.net_amount_minor),
        },
        passed=False,
    )


def match_r6_batch_to_bank_scored(
    batch: CanonicalTransaction, index: TransactionIndex, policy: Policy
) -> tuple[CanonicalTransaction | None, float | None, list[Evidence]]:
    """Amount and date window, with no reference to rely on.

    Returns `(chosen, margin, evidence)`. **The chosen candidate is
    returned even when the margin is too small**, because the case detail
    must show what was considered - but the margin travels with it, and
    the gate refuses to clear on a near-tie.

    This is the flagship abstention path: one bank credit, two settlements
    that both fit it, and no defensible way to pick.
    """
    candidates = index.candidates(
        batch,
        entity_types=(EntityType.BANK_TRANSACTION,),
        window_days=policy.settlement_window_days,
        amount_tolerance_minor=0,
    )
    credits = [c for c in candidates if c.direction.value == "credit"]

    if not credits:
        return None, None, [Evidence(
            rule_code="R6",
            evidence_type="amount_and_window",
            statement=(
                f"No bank credit matches the net within the "
                f"T+0 to T+{policy.settlement_window_days} window."
            ),
            computed={
                "batch.net": _money(batch.net_amount_minor),
                "window_days": str(policy.settlement_window_days),
                "candidates": "0",
            },
            passed=False,
        )]

    scored: list[tuple[float, CanonicalTransaction, dict[str, float]]] = []
    for candidate in credits:
        distance = (candidate.business_date - batch.business_date).days
        score, components = score_candidate(
            batch.reference_id,
            candidate.reference_id,
            amount_equal=candidate.net_amount_minor == batch.net_amount_minor,
            date_distance_days=abs(distance),
            window_days=policy.settlement_window_days,
            status_compatible=candidate.status in SETTLED_STATUSES,
            counterparty_similarity=_counterparty_similarity(batch, candidate),
        )
        scored.append((score, candidate, components))

    scored.sort(key=lambda row: (-row[0], row[1].external_id_norm))
    best_score, best, best_components = scored[0]
    margin = margin_between([s for s, _, _ in scored])

    evidence = [Evidence(
        rule_code="R6",
        evidence_type="amount_and_window",
        statement=(
            f"{len(scored)} bank credit(s) match the net exactly inside the window."
            if len(scored) > 1
            else "One bank credit matches the net exactly inside the window."
        ),
        computed={
            "candidates_in_window": str(len(scored)),
            "best_score": f"{best_score:.2f}",
            "margin_to_runner_up": "none" if margin is None else f"{margin:.2f}",
            "required_margin": f"{policy.candidate_margin:.2f}",
        },
        # Passing means "this rule produced a usable candidate", which is
        # true even when the margin then blocks resolution. Whether it is
        # safe to act on is the gate's decision, not the rule's.
        passed=True,
    )]

    for score, candidate, components in scored:
        evidence.append(Evidence(
            rule_code="R6",
            evidence_type="candidate",
            statement=(
                f"Candidate {candidate.external_id} scored {score:.2f}"
                + ("" if candidate is best else " and was not selected")
            ),
            computed={k: f"{v:.2f}" for k, v in components.items()}
            | {"bank_txn": candidate.external_id, "date": candidate.business_date.isoformat()},
            passed=candidate is best,
        ))

    return best, margin, evidence


def _counterparty_similarity(a: CanonicalTransaction, b: CanonicalTransaction) -> float:
    """Crude token overlap between counterparty and narration.

    Deliberately crude. A sophisticated string metric here would produce
    confident-looking scores from text that is often boilerplate; the
    signal carries only 0.10 of the candidate score for that reason.
    """
    left = {t for t in (a.counterparty or "").upper().split() if len(t) > 2}
    right = {t for t in ((b.counterparty or "") + " " + (b.description or "")).upper().split()
             if len(t) > 2}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left)


# --------------------------------------------------------------------------
# R3 - batch integrity
# --------------------------------------------------------------------------

def check_r3_batch_integrity(
    batch: CanonicalTransaction,
    lines: list[CanonicalTransaction],
    policy: Policy,
    line_to_payment: dict[str, CanonicalTransaction] | None = None,
) -> tuple[list[Evidence], object]:
    """Batch header against its own detail lines.

    Two separate checks, because they fail for different reasons:
    the batch total against the sum of its lines (a missing or extra
    line), and each line's own `gross - fee - tax = net` (a fee mapping
    error). Reporting them as one number would lose which happened.
    """
    bridge = build_settlement_bridge(
        batch, lines, tolerance_minor=policy.amount_tolerance_minor
    )

    evidence = [Evidence(
        rule_code="R3",
        evidence_type="amount_identity",
        statement="Sum of settlement lines equals the batch net.",
        computed={
            "line_count": str(len(lines)),
            "sum(line.net)": _money(bridge.expected_net_minor),
            "batch.net": _money(bridge.observed_net_minor),
            "difference": _money(bridge.difference_minor),
            "tolerance": _money(bridge.tolerance_minor),
        },
        passed=bridge.balances,
    )]

    failing = [
        ln for ln in lines
        if ln.gross_amount_minor - ln.fee_amount_minor - ln.tax_amount_minor
        != ln.net_amount_minor
    ]
    evidence.append(Evidence(
        rule_code="R3",
        evidence_type="fee_identity",
        statement="gross - fee - tax = net holds for every line in the batch.",
        computed={"lines_checked": str(len(lines)), "lines_failing": str(len(failing))},
        passed=not failing,
    ))

    # Internal consistency is not the same as policy correctness: a batch
    # can satisfy its own arithmetic perfectly at a rate that matches no
    # method in the fee schedule.
    #
    # The rate depends on the payment method, and the method lives on the
    # *payment*, not on the settlement line - the line inherited a fee
    # that was computed from it. Checking a line without resolving its
    # payment falls back to the default rate and then flags every UPI and
    # card batch as off-schedule, which is a wall of false positives that
    # buries the real findings. A line whose payment is unavailable is
    # skipped rather than guessed at.
    resolvable = 0
    off_schedule: list[CanonicalTransaction] = []
    for ln in lines:
        payment = (line_to_payment or {}).get(ln.external_id_norm)
        method = _method_of(payment)
        if method is None:
            continue
        resolvable += 1
        if not fee_matches_schedule(
            ln.gross_amount_minor, ln.fee_amount_minor, ln.tax_amount_minor,
            method, tolerance_minor=2,
        ):
            off_schedule.append(ln)

    evidence.append(Evidence(
        rule_code="R3",
        evidence_type="fee_schedule",
        statement="Applied fee rate is consistent with the published schedule.",
        computed={
            "lines_checked": str(resolvable),
            "lines_unresolvable": str(len(lines) - resolvable),
            "lines_off_schedule": str(len(off_schedule)),
        },
        # Vacuously true when no line's method could be resolved. Claiming
        # a pass there would assert something never actually checked.
        passed=not off_schedule and resolvable > 0,
    ))

    return evidence, bridge


def _method_of(payment: CanonicalTransaction | None) -> str | None:
    """The payment method, which is what sets the fee rate."""
    return payment.metadata.get("method") if payment else None


# --------------------------------------------------------------------------
# R4 - invoice to payment
# --------------------------------------------------------------------------

def match_r4_invoice_to_payment(
    index: TransactionIndex, policy: Policy
) -> list[MatchGroup]:
    """Shared order id plus equal amount. A clean 1:1."""
    groups: list[MatchGroup] = []

    for invoice in index.of_type(EntityType.INVOICE):
        if not invoice.reference_id or index.is_consumed(invoice):
            continue

        payments = [
            t for t in index.referencing(invoice.reference_id)
            if t.entity_type is EntityType.PAYMENT and not index.is_consumed(t)
        ]
        if len(payments) != 1:
            continue

        payment = payments[0]
        amounts_equal = payment.gross_amount_minor == invoice.gross_amount_minor
        status_agrees = (
            payment.status is TxnStatus.CAPTURED
        ) == (invoice.status is TxnStatus.CAPTURED)

        if not (amounts_equal and status_agrees):
            # A disagreement here is the status_conflict exception, raised
            # by the detector rather than silently skipped as a non-match.
            continue

        group = MatchGroup(
            group_id=f"grp_r4_{invoice.external_id_norm}",
            group_type=GroupType.ONE_TO_ONE,
            matched_by_rule="R4",
            tier=RuleTier.DETERMINISTIC,
            links=[
                Link(invoice, LinkRole.INVOICE, invoice.gross_amount_minor),
                Link(payment, LinkRole.PAYMENT, payment.gross_amount_minor),
            ],
            evidence=[Evidence(
                rule_code="R4",
                evidence_type="exact_order_and_amount",
                statement="Invoice and payment share an order id and the amounts are equal.",
                computed={
                    "order_id": invoice.reference_id,
                    "invoice.amount_due": _money(invoice.gross_amount_minor),
                    "payment.amount": _money(payment.gross_amount_minor),
                    "difference": "0",
                },
                passed=True,
            )],
            explanation=(
                f"Invoice {invoice.external_id} matches payment {payment.external_id} "
                f"on order {invoice.reference_id}."
            ),
        )
        groups.append(group)

    return groups


# --------------------------------------------------------------------------
# R5 - ledger to batch
# --------------------------------------------------------------------------

def check_r5_ledger(
    batch: CanonicalTransaction,
    entries: list[CanonicalTransaction],
    policy: Policy,
) -> tuple[list[Evidence], object | None]:
    """The journal for a batch must balance."""
    if not entries:
        return [Evidence(
            rule_code="R5",
            evidence_type="ledger_present",
            statement="No ledger entries reference this settlement.",
            computed={"batch": batch.external_id, "entries": "0"},
            passed=False,
        )], None

    bridge = build_ledger_bridge(
        batch, entries, tolerance_minor=policy.amount_tolerance_minor
    )
    return [Evidence(
        rule_code="R5",
        evidence_type="double_entry",
        statement="Journal debits equal credits for this settlement.",
        computed={
            "entries": str(len(entries)),
            "debits": _money(bridge.observed_net_minor),
            "credits": _money(bridge.expected_net_minor),
            "difference": _money(bridge.difference_minor),
        },
        passed=bridge.balances,
    )], bridge
