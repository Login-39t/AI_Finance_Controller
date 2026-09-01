"""Gateway payments and refunds.

One file carries both, discriminated by `record_type`, because that is
how the gateway exports them and splitting on read would mean two passes
over the same rows.

The join keys this sets up:
  * a refund's `parent_external_id` is its payment  -> refund linkage
  * every row's `reference_id` is its order id      -> R4, invoice match
"""

from __future__ import annotations

from collections.abc import Mapping

from ..canonical import CanonicalTransaction
from ..enums import EntityType, SourceSystem, TxnDirection, TxnStatus
from .base import (
    DEFAULT_BUSINESS_TZ,
    RejectionError,
    build,
    map_status,
    money,
    optional,
    parse_instant,
    require,
)

STATUS_MAP = {
    "created": TxnStatus.CREATED,
    "authorized": TxnStatus.AUTHORIZED,
    "authorised": TxnStatus.AUTHORIZED,
    "captured": TxnStatus.CAPTURED,
    "success": TxnStatus.CAPTURED,
    "succeeded": TxnStatus.CAPTURED,
    "paid": TxnStatus.CAPTURED,
    "failed": TxnStatus.FAILED,
    "refunded": TxnStatus.REFUNDED,
    "partially_refunded": TxnStatus.PARTIALLY_REFUNDED,
    "cancelled": TxnStatus.CANCELLED,
    "canceled": TxnStatus.CANCELLED,
    "disputed": TxnStatus.DISPUTED,
    "pending": TxnStatus.PENDING,
}


class PaymentsNormalizer:
    dataset = "payments"
    source_system = SourceSystem.GATEWAY_PAYMENTS
    entity_types = (EntityType.PAYMENT, EntityType.REFUND)
    required_columns = ("payment_id", "amount", "currency", "status", "created_at")

    def normalise(
        self, row: Mapping[str, str], *, business_timezone: str = DEFAULT_BUSINESS_TZ
    ) -> CanonicalTransaction:
        external_id = require(row, "payment_id")
        currency = require(row, "currency").upper()

        record_type = (row.get("record_type") or "payment").strip().lower()
        if record_type not in ("payment", "refund"):
            raise RejectionError(
                "UNKNOWN_RECORD_TYPE",
                f"record_type must be 'payment' or 'refund', got {record_type!r}",
                column="record_type",
                value=row.get("record_type"),
            )
        is_refund = record_type == "refund"

        parent = optional(row, "parent_payment_id")
        if is_refund and not parent:
            # A refund with no parent id is unusable as a *record*, which
            # is different from a refund whose parent is missing from the
            # dataset - that one is the refund_unlinked exception and must
            # reach the engine, not the quarantine.
            raise RejectionError(
                "MISSING_FIELD",
                "a refund must carry parent_payment_id",
                column="parent_payment_id",
            )

        gross = money(row, "amount", currency=currency)
        event_at, business_date, tz_assumed = parse_instant(
            require(row, "created_at"),
            column="created_at",
            business_timezone=business_timezone,
        )

        flags: list[str] = []
        if gross == 0:
            flags.append("zero_amount")

        return build(
            source_system=self.source_system,
            entity_type=EntityType.REFUND if is_refund else EntityType.PAYMENT,
            external_id=external_id,
            currency=currency,
            gross_amount_minor=gross,
            net_amount_minor=gross,          # gateway records carry no fee split
            # Money leaves the merchant on a refund, so a refund is a debit.
            direction=TxnDirection.DEBIT if is_refund else TxnDirection.CREDIT,
            status=map_status(require(row, "status"), STATUS_MAP),
            event_at=event_at,
            business_date=business_date,
            business_timezone=business_timezone,
            tz_assumed=tz_assumed,
            parent_external_id=parent,
            reference_id=optional(row, "order_id"),
            metadata={
                k: v for k, v in (("method", optional(row, "method")),) if v
            },
            data_quality_flags=tuple(flags),
        )
