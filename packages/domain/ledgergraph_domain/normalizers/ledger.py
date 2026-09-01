"""Internal ledger.

A journal line is single-sided: it carries either a debit or a credit,
never both. That is what makes the direction unambiguous here - unlike
the bank statement, where a direction column and a signed amount could
disagree, a ledger row's side *is* its direction.

A row with both populated is rejected rather than netted. Netting would
produce a plausible number from a row whose meaning is genuinely unclear,
which is exactly the silent coercion this layer exists to prevent.

`reference_id` is the batch the posting belongs to, which is what R5
joins on. The account code goes to `counterparty`, so the case detail can
show *which* account was posted without a second lookup.
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

DEFAULT_CURRENCY = "INR"

STATUS_MAP = {
    "posted": TxnStatus.POSTED,
    "draft": TxnStatus.CREATED,
    "pending": TxnStatus.PENDING,
    "reversed": TxnStatus.REVERSED,
    "cancelled": TxnStatus.CANCELLED,
    "canceled": TxnStatus.CANCELLED,
}


class LedgerNormalizer:
    dataset = "ledger"
    source_system = SourceSystem.INTERNAL_LEDGER
    entity_types = (EntityType.LEDGER_ENTRY,)
    required_columns = ("journal_id", "account", "debit", "credit", "posted_at")

    def normalise(
        self, row: Mapping[str, str], *, business_timezone: str = DEFAULT_BUSINESS_TZ
    ) -> CanonicalTransaction:
        currency = (optional(row, "currency") or DEFAULT_CURRENCY).upper()

        debit = money(row, "debit", currency=currency)
        credit = money(row, "credit", currency=currency)

        if debit and credit:
            raise RejectionError(
                "AMBIGUOUS_SIGN",
                f"a journal line must be single-sided; got debit={debit} and credit={credit}",
                column="debit",
                value=row.get("debit"),
            )

        # A genuinely zero line (both sides blank) is valid bookkeeping -
        # a placeholder posting - but it cannot participate in matching,
        # so it is kept and flagged rather than dropped.
        amount = debit or credit
        direction = TxnDirection.DEBIT if debit else TxnDirection.CREDIT

        event_at, business_date, tz_assumed = parse_instant(
            require(row, "posted_at"),
            column="posted_at",
            business_timezone=business_timezone,
        )

        flags: list[str] = []
        if amount == 0:
            flags.append("zero_amount")

        return build(
            source_system=self.source_system,
            entity_type=EntityType.LEDGER_ENTRY,
            external_id=require(row, "journal_id"),
            currency=currency,
            gross_amount_minor=amount,
            net_amount_minor=amount,
            direction=direction,
            status=map_status(
                optional(row, "status") or "posted", STATUS_MAP
            ),
            event_at=event_at,
            business_date=business_date,
            business_timezone=business_timezone,
            tz_assumed=tz_assumed,
            reference_id=optional(row, "reference"),     # R5 joins here
            counterparty=require(row, "account"),
            data_quality_flags=tuple(flags),
        )
