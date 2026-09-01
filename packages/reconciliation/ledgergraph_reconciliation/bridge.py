"""Amount bridge: gross - refunds - fees - taxes +/- adjustments = net.

Integer arithmetic on minor units throughout. No float appears in this
file, which is the point of the whole money layer existing.

The bridge is what turns "these two numbers differ" into "they differ by
exactly the GST on the fee" - the difference between a spreadsheet and an
explanation.
"""

from __future__ import annotations

from ledgergraph_domain.canonical import CanonicalTransaction

from .models import Bridge, BridgeComponent

#: Fee schedule, in basis points. Mirrors data/synthetic/generator.py so
#: an expectation check has something to check against; in the real system
#: this is loaded from the `fee_schedules` table, never hardcoded.
DEFAULT_FEE_BPS = 200
GST_BPS_ON_FEE = 1800
METHOD_FEE_BPS = {"upi": 150, "card": 250, "netbanking": 200, "wallet": 180}


def build_settlement_bridge(
    batch: CanonicalTransaction,
    lines: list[CanonicalTransaction],
    *,
    tolerance_minor: int,
    refunds: list[CanonicalTransaction] | None = None,
) -> Bridge:
    """The bridge for one settlement batch against its lines.

    `expected` is computed from the lines - the things that actually
    settled - and `observed` is what the batch header claims. A mismatch
    means the header and its detail disagree, which is a real finding
    rather than a rounding artefact.
    """
    gross = sum(ln.gross_amount_minor for ln in lines)
    fee = sum(ln.fee_amount_minor for ln in lines)
    tax = sum(ln.tax_amount_minor for ln in lines)
    refund_total = sum(r.gross_amount_minor for r in (refunds or ()))

    components = [
        BridgeComponent(
            label=f"Gross captured, {len(lines)} line{'s' if len(lines) != 1 else ''}",
            amount_minor=gross,
            operation="base",
            source_ref=batch.external_id,
        ),
    ]
    if refund_total:
        components.append(BridgeComponent(
            label=f"Refunds, {len(refunds or ())}",
            amount_minor=refund_total,
            operation="subtract",
            source_ref=batch.external_id,
        ))
    if fee:
        components.append(BridgeComponent(
            label="Gateway fee", amount_minor=fee, operation="subtract",
            source_ref="fee_schedule",
        ))
    if tax:
        components.append(BridgeComponent(
            label=f"GST on fee, {GST_BPS_ON_FEE / 100:.2f}%",
            amount_minor=tax, operation="subtract", source_ref="fee_schedule",
        ))

    expected = gross - refund_total - fee - tax

    return Bridge(
        currency=batch.currency,
        components=tuple(components),
        expected_net_minor=expected,
        observed_net_minor=batch.net_amount_minor,
        tolerance_minor=tolerance_minor,
    )


def build_ledger_bridge(
    batch: CanonicalTransaction,
    entries: list[CanonicalTransaction],
    *,
    tolerance_minor: int,
) -> Bridge:
    """Debits against credits for one batch's journal.

    Double entry means these must be equal. When they are not, the
    difference is diagnostic: a shortfall of exactly the batch's tax
    component is a revenue line posted net of GST, which is a specific,
    nameable error rather than a generic imbalance.
    """
    debits = [e for e in entries if e.direction.value == "debit"]
    credits = [e for e in entries if e.direction.value == "credit"]

    debit_total = sum(e.gross_amount_minor for e in debits)
    credit_total = sum(e.gross_amount_minor for e in credits)

    components = [
        BridgeComponent(
            label=f"Debits, {len(debits)} line{'s' if len(debits) != 1 else ''}",
            amount_minor=debit_total, operation="base", source_ref=batch.external_id,
        ),
        BridgeComponent(
            label=f"Credits, {len(credits)} line{'s' if len(credits) != 1 else ''}",
            amount_minor=credit_total, operation="subtract", source_ref=batch.external_id,
        ),
    ]

    return Bridge(
        currency=batch.currency,
        components=tuple(components),
        expected_net_minor=credit_total,
        observed_net_minor=debit_total,
        tolerance_minor=tolerance_minor,
    )


def expected_fee_minor(gross_minor: int, method: str | None) -> tuple[int, int]:
    """What the fee and its GST *should* be for a given method.

    Used to detect a wrong fee mapping - a batch whose internal arithmetic
    is perfectly consistent but computed at a rate that matches no method
    in the schedule. Internal consistency and policy correctness are
    different checks, and only the second one catches this.
    """
    bps = METHOD_FEE_BPS.get((method or "").lower(), DEFAULT_FEE_BPS)
    fee = gross_minor * bps // 10_000
    tax = fee * GST_BPS_ON_FEE // 10_000
    return fee, tax


def fee_matches_schedule(
    gross_minor: int, fee_minor: int, tax_minor: int, method: str | None,
    *, tolerance_minor: int = 0,
) -> bool:
    """True when the applied fee is consistent with the schedule.

    Tolerance exists because per-line rounding does not always sum to the
    batch-level computation to the paise. Any tolerance consumed is
    reported in the bridge rather than absorbed.
    """
    expected_fee, expected_tax = expected_fee_minor(gross_minor, method)
    return (
        abs(fee_minor - expected_fee) <= tolerance_minor
        and abs(tax_minor - expected_tax) <= tolerance_minor
    )
