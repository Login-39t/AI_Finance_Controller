"""Bank statement.

Two properties of bank exports drive everything here.

**Dates, not instants.** A statement gives a posting date with no time and
no offset. Anchoring it at midnight in the business timezone and flagging
`tz_assumed` is the honest normalisation; pretending it is a UTC instant
would silently shift a day at the boundary and corrupt every settlement
window comparison.

**Narration is free text, and in the real world it is
attacker-influenced.** It is preserved verbatim in `description`, and the
reference is *extracted* from it into its own column rather than the
matcher pattern-matching against prose at query time. Downstream, that
description is wrapped and labelled untrusted before it can reach a model
prompt (docs/03-architecture.md R1).
"""

from __future__ import annotations

from collections.abc import Mapping

from ..canonical import CanonicalTransaction
from ..enums import EntityType, SourceSystem, TxnDirection, TxnStatus
from .base import (
    DEFAULT_BUSINESS_TZ,
    RejectionError,
    build,
    extract_reference,
    money,
    optional,
    parse_instant,
    require,
)

DEFAULT_CURRENCY = "INR"

_DIRECTION_MAP = {
    "credit": TxnDirection.CREDIT,
    "cr": TxnDirection.CREDIT,
    "c": TxnDirection.CREDIT,
    "deposit": TxnDirection.CREDIT,
    "debit": TxnDirection.DEBIT,
    "dr": TxnDirection.DEBIT,
    "d": TxnDirection.DEBIT,
    "withdrawal": TxnDirection.DEBIT,
}


class BankStatementNormalizer:
    dataset = "bank_statement"
    source_system = SourceSystem.BANK_STATEMENT
    entity_types = (EntityType.BANK_TRANSACTION,)
    required_columns = ("bank_txn_id", "date", "amount", "direction")

    def normalise(
        self, row: Mapping[str, str], *, business_timezone: str = DEFAULT_BUSINESS_TZ
    ) -> CanonicalTransaction:
        currency = (optional(row, "currency") or DEFAULT_CURRENCY).upper()

        raw_direction = require(row, "direction").lower()
        direction = _DIRECTION_MAP.get(raw_direction)
        if direction is None:
            raise RejectionError(
                "UNKNOWN_DIRECTION",
                f"{raw_direction!r} is not a recognised direction; "
                f"known values are {sorted(set(_DIRECTION_MAP))}",
                column="direction",
                value=row.get("direction"),
            )

        # Amounts are magnitudes: the direction column is the single
        # source of sign. A statement that supplies both a sign and a
        # direction is ambiguous and must not be guessed at.
        raw_amount = (row.get("amount") or "").strip()
        if raw_amount.startswith("-") or (raw_amount.startswith("(") and raw_amount.endswith(")")):
            raise RejectionError(
                "AMBIGUOUS_SIGN",
                "amount carries a sign and the row also has a direction column; "
                "exactly one may indicate direction",
                column="amount",
                value=row.get("amount"),
            )
        amount = money(row, "amount", currency=currency)

        event_at, business_date, tz_assumed = parse_instant(
            require(row, "date"), column="date", business_timezone=business_timezone
        )

        narration = optional(row, "description")
        stated_ref = optional(row, "reference")
        reference = stated_ref or extract_reference(narration)

        flags: list[str] = []
        if not reference:
            # No extractable reference at all. Amount and date can still
            # support a scored match, but never an exact-reference one.
            flags.append("bank_reference_missing")
        elif not stated_ref:
            # Recovered from prose rather than supplied in a field, so it
            # is weaker evidence and the case detail should say so.
            flags.append("reference_extracted_from_narration")

        metadata = {}
        balance = optional(row, "balance")
        if balance is not None:
            # Kept as the source string. It is context for a human reading
            # the statement, never an input to reconciliation arithmetic.
            metadata["balance_raw"] = balance

        return build(
            source_system=self.source_system,
            entity_type=EntityType.BANK_TRANSACTION,
            external_id=require(row, "bank_txn_id"),
            currency=currency,
            gross_amount_minor=amount,
            net_amount_minor=amount,
            direction=direction,
            status=TxnStatus.POSTED,
            event_at=event_at,
            business_date=business_date,
            business_timezone=business_timezone,
            tz_assumed=tz_assumed,
            reference_id=reference,
            description=narration,
            metadata=metadata,
            data_quality_flags=tuple(flags),
        )
