"""Invoices and orders.

`reference_id` is the order id - the same key the payments normaliser
sets - so R4 joins invoice to payment on one indexed column rather than
reaching across two differently-named fields.

`gross` is the amount *due*, not the amount paid. The paid figure lives
in metadata because it is the thing under dispute: a fully-paid invoice
whose gateway payment says captured is a clean match, and one that
disagrees is the `status_conflict` exception. Storing paid as the record's
amount would make that disagreement invisible.
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

DEFAULT_CURRENCY = "INR"

STATUS_MAP = {
    "paid": TxnStatus.CAPTURED,
    "unpaid": TxnStatus.PENDING,
    "partially_paid": TxnStatus.PARTIALLY_REFUNDED,
    "pending": TxnStatus.PENDING,
    "issued": TxnStatus.CREATED,
    "draft": TxnStatus.CREATED,
    "cancelled": TxnStatus.CANCELLED,
    "canceled": TxnStatus.CANCELLED,
    "void": TxnStatus.CANCELLED,
}


class InvoicesNormalizer:
    dataset = "invoices"
    source_system = SourceSystem.INVOICES
    entity_types = (EntityType.INVOICE,)
    required_columns = ("invoice_id", "amount_due", "status", "issued_at")

    def normalise(
        self, row: Mapping[str, str], *, business_timezone: str = DEFAULT_BUSINESS_TZ
    ) -> CanonicalTransaction:
        currency = (optional(row, "currency") or DEFAULT_CURRENCY).upper()

        due = money(row, "amount_due", currency=currency)
        paid = money(row, "amount_paid", currency=currency) if "amount_paid" in row else 0

        event_at, business_date, tz_assumed = parse_instant(
            require(row, "issued_at"),
            column="issued_at",
            business_timezone=business_timezone,
        )

        flags: list[str] = []
        if paid > due:
            # Overpayment is real and needs a human; it is not a parse
            # error, so it travels as a flag rather than a rejection.
            flags.append("overpaid")
        if due == 0:
            flags.append("zero_amount")

        return build(
            source_system=self.source_system,
            entity_type=EntityType.INVOICE,
            external_id=require(row, "invoice_id"),
            currency=currency,
            gross_amount_minor=due,
            net_amount_minor=due,
            direction=TxnDirection.CREDIT,
            status=map_status(require(row, "status"), STATUS_MAP),
            event_at=event_at,
            business_date=business_date,
            business_timezone=business_timezone,
            tz_assumed=tz_assumed,
            reference_id=optional(row, "order_id"),      # R4 joins here
            customer_ref=optional(row, "customer_id"),
            metadata={"amount_paid_minor": str(paid)},
            data_quality_flags=tuple(flags),
        )
