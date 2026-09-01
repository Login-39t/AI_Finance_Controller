"""The eight exception detectors.

One per type in the blueprint's taxonomy. Each produces a case carrying
its own `amount_at_risk_minor`, which is the queue's sort key and
therefore the single most consequential number in day-to-day use - it
decides what an analyst looks at first.

Amount at risk is computed per type rather than defaulted to the
record's amount:

    missing_bank_credit   the settlement net that has not arrived
    amount_mismatch       the size of the discrepancy, not the total
    duplicate             the amount that would be double counted
    unmatched_payment     the payment that has not settled

Getting this wrong does not fail a test - it silently mis-sorts the queue
so the expensive problem sits below three cheap ones.
"""

from __future__ import annotations

from collections import defaultdict

from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import (
    EntityType,
    ExceptionSeverity,
    ExceptionType,
    TxnStatus,
)

from .index import TransactionIndex
from .models import Bridge, Evidence, ExceptionCase
from .policy import Policy


def _severity_for(amount_minor: int, policy: Policy) -> ExceptionSeverity:
    """Severity follows money, with type-specific overrides applied by callers."""
    if amount_minor > policy.review_required_above_minor:
        return ExceptionSeverity.CRITICAL
    if amount_minor > policy.auto_resolve_max_minor:
        return ExceptionSeverity.HIGH
    if amount_minor > policy.auto_resolve_max_minor // 10:
        return ExceptionSeverity.MEDIUM
    return ExceptionSeverity.LOW


def detect_missing_bank_credit(
    batch: CanonicalTransaction,
    bank: CanonicalTransaction | None,
    margin: float | None,
    evidence: list[Evidence],
    policy: Policy,
    *,
    confirmed_by_reference: bool = True,
) -> ExceptionCase | None:
    """Settlement says paid; the bank credit cannot be confirmed.

    Three distinct situations, all of which mean a human has to look:

    * **nothing found** - no credit matches the net in the window;
    * **ambiguous** - two or more credits fit equally well, so choosing
      one would be a guess;
    * **unconfirmed** - exactly one credit fits, but only on amount and
      date. Without a reference there is nothing tying *this* credit to
      *this* settlement beyond a coincidence of value and timing, and on
      a day with two payouts of similar size that coincidence is not
      rare. The money has probably arrived; which settlement it belongs
      to is unestablished, and `missing_bank_credit` sits on the policy's
      never-auto-resolve list precisely so this cannot be cleared on
      circumstantial evidence.
    """
    ambiguous = bank is not None and margin is not None and margin <= policy.candidate_margin
    unconfirmed = bank is not None and not confirmed_by_reference and not ambiguous

    if bank is not None and not ambiguous and not unconfirmed:
        return None

    if unconfirmed:
        hypothesis = (
            "A single bank credit matches the net inside the window, but the settlement "
            "carries no reference, so the link rests on amount and date alone. That is "
            "circumstantial rather than identifying."
        )
        recommendation = (
            f"Obtain the payout reference for {batch.external_id} and confirm it against "
            f"{bank.external_id}. Treat the match as unconfirmed until then."
        )
    elif ambiguous:
        hypothesis = (
            "The settlement export omits a usable reference, so the only remaining link "
            "to the bank is amount and date. More than one credit satisfies both, and the "
            "margin between them is below the threshold the policy requires."
        )
        recommendation = (
            f"Request the payout reference for {batch.external_id} from the settlement "
            "report, or ask the bank for the remitter reference on the candidate credits. "
            "Do not attribute either credit until one of those returns."
        )
    else:
        hypothesis = (
            "The settlement is marked paid but no bank credit matches its net inside the "
            "expected window."
        )
        recommendation = (
            f"Verify the payout status for {batch.external_id} and confirm the destination "
            "account."
        )

    return ExceptionCase(
        case_id=f"exc_mbc_{batch.external_id_norm}",
        case_type=ExceptionType.MISSING_BANK_CREDIT,
        severity=_severity_for(batch.net_amount_minor, policy),
        amount_at_risk_minor=batch.net_amount_minor,
        currency=batch.currency,
        primary_transaction=batch,
        transactions=[batch] + ([bank] if bank else []),
        hypothesis=hypothesis,
        recommendation=recommendation,
        evidence=evidence,
    )


def detect_amount_mismatch(
    batch: CanonicalTransaction,
    bridge: Bridge,
    evidence: list[Evidence],
    policy: Policy,
    *,
    case_type: ExceptionType = ExceptionType.AMOUNT_MISMATCH,
    hypothesis: str = "",
) -> ExceptionCase | None:
    """A bridge that does not balance beyond tolerance.

    Amount at risk is the *difference*, not the batch total. A batch of
    Rs 5,00,000 that is out by Rs 12 is a Rs 12 problem, and sorting it as
    a Rs 5,00,000 one would push genuinely large exposures down the queue.
    """
    if bridge.balances:
        return None

    difference = abs(bridge.difference_minor)
    return ExceptionCase(
        case_id=f"exc_amt_{batch.external_id_norm}",
        case_type=case_type,
        severity=_severity_for(difference, policy),
        amount_at_risk_minor=difference,
        currency=batch.currency,
        primary_transaction=batch,
        transactions=[batch],
        hypothesis=hypothesis or (
            f"Components do not reconcile to the stated net; the difference is "
            f"{difference} minor units."
        ),
        recommendation="Review the component bridge and correct the source posting.",
        evidence=evidence,
    )


def detect_unmatched_payments(
    index: TransactionIndex, policy: Policy
) -> list[ExceptionCase]:
    """Captured payments with no settlement line naming them."""
    cases: list[ExceptionCase] = []

    settled_payment_ids = {
        line.parent_external_id.strip().upper()
        for line in index.of_type(EntityType.SETTLEMENT_LINE)
        if line.parent_external_id
    }

    for payment in index.of_type(EntityType.PAYMENT):
        if payment.status is not TxnStatus.CAPTURED:
            continue                       # failed and refunded do not settle
        if payment.external_id_norm in settled_payment_ids:
            continue

        cases.append(ExceptionCase(
            case_id=f"exc_unm_{payment.external_id_norm}",
            case_type=ExceptionType.UNMATCHED_PAYMENT,
            severity=_severity_for(payment.gross_amount_minor, policy),
            amount_at_risk_minor=payment.gross_amount_minor,
            currency=payment.currency,
            primary_transaction=payment,
            transactions=[payment],
            hypothesis=(
                "Payment is captured but no settlement line references it. The settlement "
                "window may not have closed, or the export may be incomplete."
            ),
            recommendation=(
                "Recheck after the settlement window closes; if it remains unmatched, "
                "request the settlement export for the period."
            ),
            evidence=[Evidence(
                rule_code="R1",
                evidence_type="exact_parent",
                statement="No settlement line names this payment.",
                computed={
                    "payment": payment.external_id,
                    "business_date": payment.business_date.isoformat(),
                    "amount": str(payment.gross_amount_minor),
                },
                passed=False,
            )],
        ))

    return cases


def detect_duplicates(index: TransactionIndex, policy: Policy) -> list[ExceptionCase]:
    """Records that represent the same event twice.

    Detected on business content, not on primary key - a re-presented bank
    row arrives with a *new* id, which is exactly why a uniqueness
    constraint alone would not catch it.
    """
    cases: list[ExceptionCase] = []
    buckets: dict[tuple, list[CanonicalTransaction]] = defaultdict(list)

    for txn in index.of_type(EntityType.BANK_TRANSACTION, EntityType.LEDGER_ENTRY):
        if txn.gross_amount_minor == 0:
            continue
        key = (
            txn.entity_type,
            txn.net_amount_minor,
            txn.business_date,
            (txn.reference_id or "").upper(),
            txn.direction,
            (txn.counterparty or "").upper(),
        )
        buckets[key].append(txn)

    for key, members in buckets.items():
        if len(members) < 2:
            continue
        # Without a reference there is nothing distinguishing two genuinely
        # separate transactions of the same amount on the same day, so
        # calling those duplicates would manufacture false positives.
        if not key[3]:
            continue

        duplicated = members[0].net_amount_minor * (len(members) - 1)
        primary = members[0]
        cases.append(ExceptionCase(
            case_id=f"exc_dup_{primary.external_id_norm}",
            case_type=ExceptionType.DUPLICATE,
            severity=_severity_for(duplicated, policy),
            amount_at_risk_minor=duplicated,
            currency=primary.currency,
            primary_transaction=primary,
            transactions=list(members),
            hypothesis=(
                f"{len(members)} records share amount, date, direction and reference under "
                "different identifiers, which is the shape of a re-presented row."
            ),
            recommendation="Confirm the duplicate and reverse or exclude the extra posting.",
            evidence=[Evidence(
                rule_code="DUP",
                evidence_type="content_hash",
                statement="Records are identical on every business field but their id.",
                computed={
                    "ids": ", ".join(m.external_id for m in members),
                    "amount": str(primary.net_amount_minor),
                    "reference": primary.reference_id or "",
                    "date": primary.business_date.isoformat(),
                },
                passed=True,
            )],
        ))

    return cases


def detect_refund_unlinked(index: TransactionIndex, policy: Policy) -> list[ExceptionCase]:
    """Refunds whose original payment is absent from the dataset."""
    cases: list[ExceptionCase] = []

    for refund in index.of_type(EntityType.REFUND):
        if index.get(refund.parent_external_id) is not None:
            continue

        cases.append(ExceptionCase(
            case_id=f"exc_rfn_{refund.external_id_norm}",
            case_type=ExceptionType.REFUND_UNLINKED,
            severity=_severity_for(refund.gross_amount_minor, policy),
            amount_at_risk_minor=refund.gross_amount_minor,
            currency=refund.currency,
            primary_transaction=refund,
            transactions=[refund],
            hypothesis=(
                "The refund names an original payment that is not present in this dataset. "
                "It was most likely captured before the imported period."
            ),
            recommendation=(
                "Import the period containing the original payment before resolving. Do not "
                "net this refund against another payment."
            ),
            evidence=[Evidence(
                rule_code="R1",
                evidence_type="missing_source_data",
                statement="The named parent payment is not in this dataset.",
                computed={
                    "refund": refund.external_id,
                    "parent_payment_id": refund.parent_external_id or "",
                },
                passed=False,
            )],
        ))

    return cases


def detect_status_conflicts(index: TransactionIndex, policy: Policy) -> list[ExceptionCase]:
    """Two systems describing the same order differently."""
    cases: list[ExceptionCase] = []

    for invoice in index.of_type(EntityType.INVOICE):
        if not invoice.reference_id:
            continue
        payments = [
            t for t in index.referencing(invoice.reference_id)
            if t.entity_type is EntityType.PAYMENT
        ]
        if len(payments) != 1:
            continue

        payment = payments[0]
        if payment.status is TxnStatus.CAPTURED and invoice.status is not TxnStatus.CAPTURED:
            cases.append(ExceptionCase(
                case_id=f"exc_sts_{invoice.external_id_norm}",
                case_type=ExceptionType.STATUS_CONFLICT,
                severity=_severity_for(payment.gross_amount_minor, policy),
                amount_at_risk_minor=payment.gross_amount_minor,
                currency=payment.currency,
                primary_transaction=invoice,
                transactions=[invoice, payment],
                hypothesis=(
                    "The gateway reports the payment captured while the invoice system still "
                    "shows the order unpaid, which is the shape of a failed webhook or sync."
                ),
                recommendation="Re-sync the invoice from the gateway and confirm the order state.",
                evidence=[Evidence(
                    rule_code="R4",
                    evidence_type="status_agreement",
                    statement="Gateway status and invoice status disagree for one order.",
                    computed={
                        "order_id": invoice.reference_id,
                        "payment.status": payment.status.value,
                        "invoice.status": invoice.status.value,
                        "amount": str(payment.gross_amount_minor),
                    },
                    passed=False,
                )],
            ))

    return cases


def detect_date_mismatch(
    batch: CanonicalTransaction,
    bank: CanonicalTransaction,
    policy: Policy,
) -> ExceptionCase | None:
    """Totals reconcile, timing does not.

    Amount at risk is zero: the money arrived and the arithmetic is
    correct. Raising it as a case is still right, because an unexplained
    timing shift is a control finding - but sorting it by value would
    wrongly put it near the top of the queue.
    """
    distance = (bank.business_date - batch.business_date).days
    if 0 <= distance <= policy.settlement_window_days:
        return None

    return ExceptionCase(
        case_id=f"exc_dat_{batch.external_id_norm}",
        case_type=ExceptionType.DATE_MISMATCH,
        severity=ExceptionSeverity.LOW,
        amount_at_risk_minor=0,
        currency=batch.currency,
        primary_transaction=batch,
        transactions=[batch, bank],
        hypothesis=(
            f"The bank credit matches exactly but posted {distance} days after settlement, "
            f"outside the T+0 to T+{policy.settlement_window_days} window."
        ),
        recommendation=(
            "Accept as a documented timing variance, or confirm the delay with the bank."
        ),
        evidence=[Evidence(
            rule_code="R2",
            evidence_type="date_window",
            statement="Amounts match exactly; the settlement date is outside the window.",
            computed={
                "settled_on": batch.business_date.isoformat(),
                "credited_on": bank.business_date.isoformat(),
                "distance_days": str(distance),
                "window_days": str(policy.settlement_window_days),
            },
            passed=False,
        )],
    )


def detect_delayed_settlement(
    batch: CanonicalTransaction,
    payments: list[CanonicalTransaction],
    policy: Policy,
) -> ExceptionCase | None:
    """Settlement later than the window allows, measured from capture.

    The window is a promise about how long money takes to travel from a
    customer's payment to the merchant's bank. So the lag that matters is
    *batch date minus the latest payment it settles*, not batch date
    minus bank date.

    Those two are easy to confuse and they fail differently: when a whole
    payout run slips, the batch and its bank credit move together, so the
    batch-to-bank distance stays zero and a check written that way sees a
    perfectly healthy settlement. Every record still reconciles to the
    paise, so nothing else objects either, and the delay clears silently.
    """
    if not payments:
        return None

    latest_capture = max(p.business_date for p in payments)
    lag = (batch.business_date - latest_capture).days
    if lag <= policy.settlement_window_days:
        return None

    return ExceptionCase(
        case_id=f"exc_lag_{batch.external_id_norm}",
        case_type=ExceptionType.DATE_MISMATCH,
        severity=ExceptionSeverity.MEDIUM,
        # The money arrived and the arithmetic is right; this is a timing
        # control finding, so it must not outrank real exposure in the queue.
        amount_at_risk_minor=0,
        currency=batch.currency,
        primary_transaction=batch,
        transactions=[batch, *payments[:5]],
        hypothesis=(
            f"The batch settled {lag} days after its latest payment capture, outside the "
            f"T+0 to T+{policy.settlement_window_days} window. Amounts reconcile exactly, "
            "so this is a timing variance rather than a shortfall."
        ),
        recommendation=(
            "Confirm the payout schedule for this period. Accept as a documented timing "
            "variance if the delay is explained."
        ),
        evidence=[Evidence(
            rule_code="R2",
            evidence_type="settlement_window",
            statement="Settlement date is within the expected window of the payment capture.",
            computed={
                "latest_capture": latest_capture.isoformat(),
                "settled_on": batch.business_date.isoformat(),
                "lag_days": str(lag),
                "window_days": str(policy.settlement_window_days),
            },
            passed=False,
        )],
    )


def detect_fee_tax_discrepancy(
    batch: CanonicalTransaction,
    evidence: list[Evidence],
    policy: Policy,
) -> ExceptionCase | None:
    """A fee rate that matches no method in the published schedule.

    The batch's own arithmetic is consistent, which is what makes this
    worth a separate detector: an internal-consistency check passes it,
    and only a comparison against policy catches it.
    """
    schedule_evidence = next(
        (e for e in evidence if e.evidence_type == "fee_schedule"), None
    )
    if schedule_evidence is None or schedule_evidence.passed:
        return None

    return ExceptionCase(
        case_id=f"exc_fee_{batch.external_id_norm}",
        case_type=ExceptionType.FEE_TAX_DISCREPANCY,
        severity=_severity_for(batch.fee_amount_minor + batch.tax_amount_minor, policy),
        amount_at_risk_minor=batch.fee_amount_minor + batch.tax_amount_minor,
        currency=batch.currency,
        primary_transaction=batch,
        transactions=[batch],
        hypothesis=(
            "The applied fee is internally consistent but does not match the rate the "
            "schedule specifies for the payment methods in this batch."
        ),
        recommendation="Verify the fee schedule and the method mapping with the gateway.",
        evidence=[schedule_evidence],
    )


def detect_ledger_mismatch(
    batch: CanonicalTransaction,
    bridge: Bridge,
    entries: list[CanonicalTransaction],
    evidence: list[Evidence],
    policy: Policy,
) -> ExceptionCase | None:
    """An unbalanced journal, with the difference named where possible."""
    if bridge.balances:
        return None

    difference = abs(bridge.difference_minor)
    # A shortfall of exactly the tax component is a specific, nameable
    # error rather than a generic imbalance, and saying so saves the
    # analyst the arithmetic.
    if difference == batch.tax_amount_minor and batch.tax_amount_minor:
        hypothesis = (
            "Credits fall short of debits by exactly the GST on the gateway fee, which is "
            "the signature of revenue posted net of tax rather than gross."
        )
    else:
        hypothesis = (
            f"Journal debits and credits differ by {difference} minor units for this "
            "settlement."
        )

    case = detect_amount_mismatch(
        batch, bridge, evidence, policy, hypothesis=hypothesis
    )
    if case is not None:
        case.case_id = f"exc_led_{batch.external_id_norm}"
        case.transactions = [batch, *entries]
    return case
