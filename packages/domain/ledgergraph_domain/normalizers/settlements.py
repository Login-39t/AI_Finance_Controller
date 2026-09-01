"""Settlement batches and their lines.

Two normalisers, one source system. They are separate because the two
files have genuinely different shapes and different join roles:

  * a **batch** is the payout. Its `reference_id` is the bank UTR, which
    is what R2 joins to the bank statement on. A blank UTR is not a bad
    row - it is the `missing_bank_credit` case, and it has to reach the
    engine intact.

  * a **line** is one payment inside that payout. Its
    `parent_external_id` is the payment (R1) and its `reference_id` is
    the batch (grouping). Both are columns rather than metadata so the
    matching SQL can join on an index.

Both carry the gross/fee/tax/net split, and `build()` enforces
`net == gross - fee - tax` on every row - so a fee-mapping error fails
here rather than surfacing as an unexplained shortfall three stages later.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..canonical import CanonicalTransaction
from ..enums import EntityType, SourceSystem, TxnDirection, TxnStatus
from .base import (
    DEFAULT_BUSINESS_TZ,
    build,
    map_status,
    money,
    optional,
    parse_instant,
    require,
)

STATUS_MAP = {
    "settled": TxnStatus.SETTLED,
    "processed": TxnStatus.SETTLED,
    "paid": TxnStatus.SETTLED,
    "pending": TxnStatus.PENDING,
    "created": TxnStatus.CREATED,
    "failed": TxnStatus.FAILED,
    "reversed": TxnStatus.REVERSED,
}

DEFAULT_CURRENCY = "INR"


class SettlementBatchNormalizer:
    dataset = "settlement_batches"
    source_system = SourceSystem.RAZORPAY_SETTLEMENTS
    entity_types = (EntityType.SETTLEMENT_BATCH,)
    required_columns = ("batch_id", "gross", "fee", "tax", "net", "status", "settled_at")

    def normalise(
        self, row: Mapping[str, str], *, business_timezone: str = DEFAULT_BUSINESS_TZ
    ) -> CanonicalTransaction:
        currency = (optional(row, "currency") or DEFAULT_CURRENCY).upper()

        gross = money(row, "gross", currency=currency)
        fee = money(row, "fee", currency=currency)
        tax = money(row, "tax", currency=currency)
        net = money(row, "net", currency=currency)

        event_at, business_date, tz_assumed = parse_instant(
            require(row, "settled_at"),
            column="settled_at",
            business_timezone=business_timezone,
        )

        utr = optional(row, "payout_utr")
        flags: list[str] = []
        if not utr:
            # The signal that drives the missing_bank_credit case. Flagged,
            # not rejected - and a non-empty flag set blocks auto-resolution
            # regardless of how well the amounts line up.
            flags.append("settlement_utr_missing")

        return build(
            source_system=self.source_system,
            entity_type=EntityType.SETTLEMENT_BATCH,
            external_id=require(row, "batch_id"),
            currency=currency,
            gross_amount_minor=gross,
            fee_amount_minor=fee,
            tax_amount_minor=tax,
            net_amount_minor=net,
            direction=TxnDirection.CREDIT,
            status=map_status(require(row, "status"), STATUS_MAP),
            event_at=event_at,
            business_date=business_date,
            business_timezone=business_timezone,
            tz_assumed=tz_assumed,
            reference_id=utr,
            data_quality_flags=tuple(flags),
        )


class SettlementLineNormalizer:
    dataset = "settlement_lines"
    source_system = SourceSystem.RAZORPAY_SETTLEMENTS
    entity_types = (EntityType.SETTLEMENT_LINE,)
    required_columns = (
        "settlement_id", "batch_id", "payment_id", "gross", "fee", "tax", "net",
    )

    def normalise(
        self, row: Mapping[str, str], *, business_timezone: str = DEFAULT_BUSINESS_TZ
    ) -> CanonicalTransaction:
        currency = (optional(row, "currency") or DEFAULT_CURRENCY).upper()

        gross = money(row, "gross", currency=currency)
        fee = money(row, "fee", currency=currency)
        tax = money(row, "tax", currency=currency)
        net = money(row, "net", currency=currency)

        batch_id = require(row, "batch_id")

        # A line export usually has no timestamp of its own; it inherits
        # its batch's settlement date. Where the column exists we use it,
        # otherwise the batch date is derived from the batch id suffix
        # rather than invented from the clock.
        raw_when = optional(row, "settled_at") or _date_from_batch_id(batch_id)
        event_at, business_date, tz_assumed = parse_instant(
            raw_when, column="settled_at", business_timezone=business_timezone
        )

        return build(
            source_system=self.source_system,
            entity_type=EntityType.SETTLEMENT_LINE,
            external_id=require(row, "settlement_id"),
            currency=currency,
            gross_amount_minor=gross,
            fee_amount_minor=fee,
            tax_amount_minor=tax,
            net_amount_minor=net,
            direction=TxnDirection.CREDIT,
            status=TxnStatus.SETTLED,
            event_at=event_at,
            business_date=business_date,
            business_timezone=business_timezone,
            tz_assumed=tz_assumed,
            parent_external_id=require(row, "payment_id"),   # R1 joins here
            reference_id=batch_id,                           # grouping joins here
        )


def _date_from_batch_id(batch_id: str) -> str:
    """`setl_20260304` -> `2026-03-04`.

    Falls back to the raw id when the shape does not match, which then
    fails `parse_instant` as an INVALID_DATE rejection naming the real
    problem, rather than being silently defaulted to today.
    """
    suffix = batch_id.removeprefix("setl_")
    if len(suffix) == 8 and suffix.isdigit():
        return f"{suffix[:4]}-{suffix[4:6]}-{suffix[6:8]}"
    return batch_id
