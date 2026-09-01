"""Run orchestration.

`execute()` is a pure function of its inputs: the same transactions and
the same ruleset version produce the same result, every time. That is
what makes a run reproducible and what lets the evaluation harness call
the real engine without a database, a server, or an event loop.

Stage order is the rule ladder, strongest evidence first. Once a
transaction is consumed by a rule, weaker rules cannot reconsider it -
otherwise the same money is counted twice and the reconciliation rate
flatters itself.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import (
    EntityType,
    ExceptionType,
    GroupType,
    LinkRole,
    RuleTier,
)

from . import exceptions as detect
from .index import TransactionIndex
from .models import Evidence, ExceptionCase, Link, MatchGroup, RunResult
from .policy import Policy
from .rules import (
    check_r3_batch_integrity,
    check_r5_ledger,
    match_r1_payment_to_line,
    match_r2_batch_to_bank,
    match_r4_invoice_to_payment,
    match_r6_batch_to_bank_scored,
)
from .scoring import score_group

RULESET_VERSION = "rules@1.4.0"


def execute(
    transactions: Iterable[CanonicalTransaction],
    *,
    run_id: str = "run_local",
    policy: Policy | None = None,
    ruleset_version: str = RULESET_VERSION,
) -> RunResult:
    """Reconcile a set of canonical transactions."""
    policy = policy or Policy()
    index = TransactionIndex(transactions)
    result = RunResult(
        run_id=run_id, ruleset_version=ruleset_version, records_processed=len(index)
    )

    _stage(result, "settlement_chain", lambda: _reconcile_settlements(index, policy, result))
    _stage(result, "invoice_match", lambda: _reconcile_invoices(index, policy, result))
    _stage(result, "exceptions", lambda: _detect_standalone(index, policy, result))
    _stage(result, "queue_integrity", lambda: _ensure_every_review_is_queued(result, policy))

    # Highest financial risk first. This ordering is the queue's contract
    # with the analyst, so it is applied here rather than left to a caller.
    result.cases.sort(key=lambda c: (-c.amount_at_risk_minor, c.case_id))
    return result


def _stage(result: RunResult, name: str, fn) -> None:
    started = time.perf_counter()
    fn()
    result.stage_timings_ms[name] = int((time.perf_counter() - started) * 1000)


# --------------------------------------------------------------------------
# The settlement chain: payment -> line -> batch -> bank -> ledger
# --------------------------------------------------------------------------

def _reconcile_settlements(
    index: TransactionIndex, policy: Policy, result: RunResult
) -> None:
    line_to_payment = match_r1_payment_to_line(index)

    for batch in index.of_type(EntityType.SETTLEMENT_BATCH):
        lines = [
            t for t in index.referencing(batch.external_id)
            if t.entity_type is EntityType.SETTLEMENT_LINE
        ]
        ledger_entries = [
            t for t in index.referencing(batch.external_id)
            if t.entity_type is EntityType.LEDGER_ENTRY
        ]

        evidence: list[Evidence] = []
        links: list[Link] = [Link(batch, LinkRole.SETTLEMENT_BATCH, batch.net_amount_minor)]

        # R1: attach each line and the payment it settles.
        matched_lines = 0
        for line in lines:
            links.append(Link(line, LinkRole.SETTLEMENT_LINE, line.net_amount_minor))
            payment = line_to_payment.get(line.external_id_norm)
            if payment is not None:
                links.append(Link(payment, LinkRole.PAYMENT, payment.gross_amount_minor))
                matched_lines += 1

        evidence.append(Evidence(
            rule_code="R1",
            evidence_type="exact_parent",
            statement="Each settlement line names a payment present in this run.",
            computed={
                "lines": str(len(lines)),
                "lines_linked_to_a_payment": str(matched_lines),
            },
            passed=bool(lines) and matched_lines == len(lines),
        ))

        # R3: the batch against its own detail. The payment map goes in
        # because the fee rate depends on the payment method, which the
        # line does not carry.
        r3_evidence, bridge = check_r3_batch_integrity(
            batch, lines, policy, line_to_payment
        )
        evidence.extend(r3_evidence)

        # R2 then R6: the bank link, strongest evidence first.
        rule = "R2"
        tier = RuleTier.DETERMINISTIC
        margin: float | None = None

        bank, r2_evidence = match_r2_batch_to_bank(batch, index)
        evidence.append(r2_evidence)

        if bank is None:
            rule, tier = "R6", RuleTier.SCORED
            bank, margin, r6_evidence = match_r6_batch_to_bank_scored(batch, index, policy)
            evidence.extend(r6_evidence)

        if bank is not None:
            links.append(Link(bank, LinkRole.BANK_CREDIT, bank.net_amount_minor))

        # R5: the journal.
        r5_evidence, ledger_bridge = check_r5_ledger(batch, ledger_entries, policy)
        evidence.extend(r5_evidence)
        for entry in ledger_entries:
            role = (
                LinkRole.LEDGER_DEBIT if entry.direction.value == "debit"
                else LinkRole.LEDGER_CREDIT
            )
            links.append(Link(entry, role, entry.gross_amount_minor))

        group = MatchGroup(
            group_id=f"grp_{batch.external_id_norm}",
            group_type=GroupType.MANY_TO_MANY,
            matched_by_rule=rule,
            tier=tier,
            links=links,
            evidence=evidence,
            bridge=bridge,
            explanation=(
                f"Settlement {batch.external_id}: {len(lines)} line(s), "
                f"{'bank credit ' + bank.external_id if bank else 'no bank credit'}, "
                f"{len(ledger_entries)} journal line(s)."
            ),
        )

        # Which exception type applies decides whether the block list bites,
        # and how much is actually at risk decides the materiality check.
        payments = [ln.transaction for ln in links if ln.role is LinkRole.PAYMENT]
        case_type = _classify(
            batch, bank, margin, bridge, ledger_bridge, evidence, policy, payments
        )
        at_risk = _amount_at_risk(case_type, batch, bridge, ledger_bridge)

        group.confidence, group.confidence_components = score_group(
            group, bridge=bridge, margin_to_runner_up=margin,
            candidate_margin=policy.candidate_margin,
        )

        from .policy import apply_gate
        apply_gate(
            group, policy,
            case_type=case_type,
            margin_to_runner_up=margin,
            amount_at_risk_minor=at_risk,
        )

        result.groups.append(group)
        index.consume(*(link.transaction for link in links))

        _raise_cases(
            result, batch, bank, margin, bridge, ledger_bridge,
            ledger_entries, evidence, group, policy,
        )


def _classify(
    batch, bank, margin, bridge, ledger_bridge, evidence, policy: Policy,
    payments=(),
) -> ExceptionType | None:
    """The exception type this group would raise, if any.

    Ordered by severity of consequence, not by detection order: a missing
    bank credit outranks a fee discrepancy, because money that has not
    arrived matters more than money charged at the wrong rate.
    """
    # No credit, an ambiguous one, or one linked on amount and date
    # alone all mean the bank leg is unconfirmed.
    if (
        bank is None
        or (margin is not None and margin <= policy.candidate_margin)
        or not batch.reference_id
    ):
        return ExceptionType.MISSING_BANK_CREDIT
    if bridge is not None and not bridge.balances:
        return ExceptionType.AMOUNT_MISMATCH
    if ledger_bridge is not None and not ledger_bridge.balances:
        return ExceptionType.AMOUNT_MISMATCH
    schedule = next((e for e in evidence if e.evidence_type == "fee_schedule"), None)
    if schedule is not None and not schedule.passed:
        return ExceptionType.FEE_TAX_DISCREPANCY
    if bank is not None:
        distance = (bank.business_date - batch.business_date).days
        if not (0 <= distance <= policy.settlement_window_days):
            return ExceptionType.DATE_MISMATCH
    # Measured from capture, not from the batch's own bank credit: when
    # a payout run slips, both move together and the gap between them
    # stays zero.
    if payments:
        lag = (batch.business_date - max(p.business_date for p in payments)).days
        if lag > policy.settlement_window_days:
            return ExceptionType.DATE_MISMATCH
    return None


def _amount_at_risk(
    case_type: ExceptionType | None,
    batch: CanonicalTransaction,
    bridge,
    ledger_bridge,
) -> int:
    """Money genuinely exposed, which is not the same as money involved.

    A batch that reconciles exactly has zero exposure regardless of its
    size. A batch whose bridge is out by Rs 42 is a Rs 42 problem, not a
    Rs 4,00,000 one. Conflating the two is what would make the gate hold
    every large clean payout while waving through a small broken one.
    """
    if case_type is None:
        return 0
    if case_type is ExceptionType.MISSING_BANK_CREDIT:
        # Here the whole payout is genuinely unaccounted for.
        return batch.net_amount_minor
    if case_type is ExceptionType.AMOUNT_MISMATCH:
        diffs = [
            abs(b.difference_minor)
            for b in (bridge, ledger_bridge)
            if b is not None and not b.balances
        ]
        return max(diffs, default=0)
    if case_type is ExceptionType.FEE_TAX_DISCREPANCY:
        return batch.fee_amount_minor + batch.tax_amount_minor
    if case_type is ExceptionType.DATE_MISMATCH:
        # The money arrived and the arithmetic is right; only timing is off.
        return 0
    return 0


def _raise_cases(
    result, batch, bank, margin, bridge, ledger_bridge,
    ledger_entries, evidence, group, policy: Policy,
) -> None:
    case = detect.detect_missing_bank_credit(
        batch, bank, margin, evidence, policy,
        confirmed_by_reference=bool(batch.reference_id),
    )
    if case is not None:
        case.group, case.confidence = group, group.confidence
        result.cases.append(case)
        return   # the missing money is the finding; do not also raise timing

    if bridge is not None:
        case = detect.detect_amount_mismatch(batch, bridge, evidence, policy)
        if case is not None:
            case.group, case.confidence = group, group.confidence
            result.cases.append(case)

    if ledger_bridge is not None:
        case = detect.detect_ledger_mismatch(
            batch, ledger_bridge, ledger_entries, evidence, policy
        )
        if case is not None:
            case.group, case.confidence = group, group.confidence
            result.cases.append(case)

    case = detect.detect_fee_tax_discrepancy(batch, evidence, policy)
    if case is not None:
        case.group, case.confidence = group, group.confidence
        result.cases.append(case)

    if bank is not None:
        case = detect.detect_date_mismatch(batch, bank, policy)
        if case is not None:
            case.group, case.confidence = group, group.confidence
            result.cases.append(case)

    payments = [ln.transaction for ln in group.links if ln.role is LinkRole.PAYMENT]
    case = detect.detect_delayed_settlement(batch, payments, policy)
    if case is not None:
        case.group, case.confidence = group, group.confidence
        result.cases.append(case)


# --------------------------------------------------------------------------
# Invoices and standalone detectors
# --------------------------------------------------------------------------

def _reconcile_invoices(index: TransactionIndex, policy: Policy, result: RunResult) -> None:
    from .policy import apply_gate

    for group in match_r4_invoice_to_payment(index, policy):
        group.confidence, group.confidence_components = score_group(group)
        apply_gate(group, policy)
        result.groups.append(group)
        # Invoices link to payments already consumed by the settlement
        # chain, so only the invoice itself is claimed here.
        index.consume(*group.role_of(LinkRole.INVOICE))


def _ensure_every_review_is_queued(result: RunResult, policy: Policy) -> None:
    """No group may need a human without appearing in the queue.

    A group the gate sent to review, with no exception case pointing at
    it, is work nobody can find: it is not auto-resolved, so it is not
    done, and it is not in the queue, so it is not going to be. The
    numbers still look fine - the reconciliation rate counts it as
    not-cleared - which is what makes it easy to miss.

    This is a backstop, not the primary path. A detector producing a
    specific, well-named case is always better than the generic one built
    here, and if this fires often that is a signal a detector is missing
    rather than that the backstop is working.
    """
    from ledgergraph_domain.enums import ExceptionSeverity, ExceptionType, GroupStatus

    queued = {case.group.group_id for case in result.cases if case.group is not None}

    for group in result.groups:
        if group.status is not GroupStatus.PENDING_REVIEW or group.group_id in queued:
            continue

        failed = [c for c in group.gate if not c.passed]
        reasons = "; ".join(f"{c.label} ({c.detail})" for c in failed) or "unspecified"
        primary = group.links[0].transaction if group.links else None
        amount = group.total_amount_minor

        result.cases.append(ExceptionCase(
            case_id=f"exc_rev_{group.group_id}",
            case_type=ExceptionType.STATUS_CONFLICT,
            severity=(
                ExceptionSeverity.HIGH
                if amount > policy.auto_resolve_max_minor
                else ExceptionSeverity.MEDIUM
            ),
            amount_at_risk_minor=amount,
            currency=group.currency,
            primary_transaction=primary,
            transactions=[link.transaction for link in group.links],
            group=group,
            confidence=group.confidence,
            hypothesis=(
                f"The group matched on {group.matched_by_rule} but did not clear the "
                f"auto-resolution gate: {reasons}."
            ),
            recommendation="Review the evidence and decide manually.",
            evidence=group.evidence,
        ))


def _detect_standalone(index: TransactionIndex, policy: Policy, result: RunResult) -> None:
    result.cases.extend(detect.detect_unmatched_payments(index, policy))
    result.cases.extend(detect.detect_duplicates(index, policy))
    result.cases.extend(detect.detect_refund_unlinked(index, policy))
    result.cases.extend(detect.detect_status_conflicts(index, policy))
