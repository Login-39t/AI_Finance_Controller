"""The canonical transaction.

One wide shape that every source normalises into, discriminated by
`entity_type` - the same single-table design as `canonical_transactions`
in `db/schema.sql`, and for the same reason: matching is a self-join, and
five separate shapes would mean a different join per rule.

Frozen, because normalisation is a pure transformation. A record that
needs correcting is re-normalised from its preserved source row, never
edited in place.

The invariants enforced in `__post_init__` are the same ones the database
enforces as CHECK constraints. Having them in both places is deliberate:
the database is the guarantee, this is the fast feedback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from .enums import EntityType, SourceSystem, TxnDirection, TxnStatus

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

#: Entities that may carry a fee or tax component. Mirrors the
#: ck_canon_fee_scope CHECK in db/schema.sql - a bank transaction with a
#: fee is a normalisation bug, not a real record.
FEE_BEARING = frozenset({
    EntityType.SETTLEMENT_BATCH,
    EntityType.SETTLEMENT_LINE,
    EntityType.ADJUSTMENT,
})


class CanonicalError(ValueError):
    """An invariant violation, carrying a stable code for the rejection report."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CanonicalTransaction:
    """A source row, normalised.

    Field semantics worth pinning down, because two of them are reused
    across sources in a way that only makes sense once stated:

    `parent_external_id` - the record this one is a child of, in the
    *same* conceptual chain. A refund's parent is its payment; a
    settlement line's parent is the payment it settles. This is what R1
    joins on.

    `reference_id` - the identifier this record points at in *another*
    system. For a settlement line that is its batch; for a batch, the bank
    UTR; for a bank transaction, the UTR extracted from its narration; for
    a payment and an invoice, the shared order id. This is what R2, R4 and
    R5 join on.
    """

    # -- identity ---------------------------------------------------------
    source_system: SourceSystem
    entity_type: EntityType
    external_id: str
    #: Join key. Trimmed and uppercased; `external_id` keeps the original
    #: for display and audit. Stored rather than computed so the join can
    #: use an index (see docs/04-database-design.md 4.1).
    external_id_norm: str = field(init=False)

    # -- money. Integer minor units, always. -------------------------------
    currency: str
    gross_amount_minor: int
    net_amount_minor: int
    direction: TxnDirection
    status: TxnStatus
    fee_amount_minor: int = 0
    tax_amount_minor: int = 0

    # -- time -------------------------------------------------------------
    #: Instant, UTC. Compare on `business_date`, never on this.
    event_at: datetime = field(kw_only=True)
    #: Date in `business_timezone`. Stored, not derived on read - see
    #: docs/04-database-design.md 1.5 for why it cannot be a generated column.
    business_date: date = field(kw_only=True)
    business_timezone: str = field(default="Asia/Kolkata", kw_only=True)
    #: True when the source timestamp carried no offset and the business
    #: timezone was assumed. Surfaced in the UI so the assumption is visible.
    #:
    #: Deliberately its own field rather than a `data_quality_flags` entry.
    #: Nearly every real source is date-only or offset-free - bank
    #: statements always, most gateway exports often - so flagging it would
    #: mark the entire dataset and, because a non-empty flag set blocks
    #: auto-resolution, drive the auto-resolution rate to zero. An assumed
    #: timezone is provenance, not a defect.
    tz_assumed: bool = field(default=False, kw_only=True)
    available_at: datetime | None = field(default=None, kw_only=True)

    # -- links ------------------------------------------------------------
    parent_external_id: str | None = field(default=None, kw_only=True)
    reference_id: str | None = field(default=None, kw_only=True)
    customer_ref: str | None = field(default=None, kw_only=True)

    # -- context ----------------------------------------------------------
    counterparty: str | None = field(default=None, kw_only=True)
    #: Bank narration and similar free text. Attacker-influenced in the
    #: real world, so it is wrapped and labelled untrusted before it ever
    #: reaches a model prompt (see docs/03-architecture.md R1).
    description: str | None = field(default=None, kw_only=True)
    metadata: dict[str, str] = field(default_factory=dict, kw_only=True)
    #: Reserved for conditions that should *block auto-resolution*: a
    #: missing settlement UTR, a zero amount, conflicting values. It is not
    #: a place for provenance notes - anything that would be set on most
    #: records makes the flag meaningless and stops the system clearing
    #: anything at all. When in doubt, add a field, not a flag.
    data_quality_flags: tuple[str, ...] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_id_norm", self.external_id.strip().upper())

        if not self.external_id.strip():
            raise CanonicalError("MISSING_FIELD", "external_id is required")

        if not _CURRENCY_RE.match(self.currency):
            raise CanonicalError(
                "INVALID_CURRENCY",
                f"currency must be three uppercase letters, got {self.currency!r}",
            )

        for name in ("gross_amount_minor", "fee_amount_minor",
                     "tax_amount_minor", "net_amount_minor"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise CanonicalError(
                    "AMOUNT_NOT_INT", f"{name} must be an int of minor units, got {value!r}"
                )

        if min(self.gross_amount_minor, self.fee_amount_minor, self.tax_amount_minor) < 0:
            raise CanonicalError(
                "AMOUNT_NEGATIVE",
                "amounts are magnitudes; sign belongs to `direction`",
            )

        # The universal identity. Entities without fees carry 0/0, so this
        # reduces to net == gross for them and still holds.
        expected = self.gross_amount_minor - self.fee_amount_minor - self.tax_amount_minor
        if self.net_amount_minor != expected:
            raise CanonicalError(
                "AMOUNT_IDENTITY_VIOLATION",
                f"net must equal gross - fee - tax: "
                f"{self.gross_amount_minor} - {self.fee_amount_minor} - "
                f"{self.tax_amount_minor} = {expected}, got {self.net_amount_minor}",
            )

        if self.entity_type not in FEE_BEARING and (self.fee_amount_minor or self.tax_amount_minor):
            raise CanonicalError(
                "FEE_OUT_OF_SCOPE",
                f"{self.entity_type.value} may not carry a fee or tax component",
            )

        if self.event_at.tzinfo is None:
            raise CanonicalError(
                "NAIVE_TIMESTAMP",
                "event_at must be timezone-aware; normalise before constructing",
            )
        if self.event_at.utcoffset() != UTC.utcoffset(None):
            raise CanonicalError(
                "NON_UTC_TIMESTAMP",
                f"event_at must be UTC, got offset {self.event_at.utcoffset()}",
            )

    @property
    def is_zero_amount(self) -> bool:
        """Valid, but excluded from matching and flagged for data quality."""
        return self.gross_amount_minor == 0

    @property
    def signed_net_minor(self) -> int:
        """Net with the direction applied. For display and bridges only."""
        return -self.net_amount_minor if self.direction is TxnDirection.DEBIT \
            else self.net_amount_minor

    def with_flag(self, flag: str) -> CanonicalTransaction:
        """Return a copy carrying an additional data-quality flag.

        A non-empty flag set caps confidence at 0.75 and blocks
        auto-resolution outright (docs/03-architecture.md section 8).
        """
        if flag in self.data_quality_flags:
            return self
        from dataclasses import replace
        return replace(self, data_quality_flags=(*self.data_quality_flags, flag))
