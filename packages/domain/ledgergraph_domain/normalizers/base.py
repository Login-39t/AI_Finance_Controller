"""Shared normalisation machinery.

Everything here is a pure function of its inputs. No database, no
framework, no clock reads that would make a normalisation depend on when
it ran - `packages/` must stay importable by the evaluation harness
without booting anything.

The contract every normaliser follows:

    normalise(row) -> CanonicalTransaction        # accepted
    normalise(row) -> raises RejectionError       # quarantined

A raised `RejectionError` carries the column, the offending value, and a
stable code, which is exactly the shape `import_rejections` stores and the
rejection report renders. Nothing is ever coerced into looking valid.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from ..canonical import CanonicalError, CanonicalTransaction
from ..enums import EntityType, SourceSystem, TxnStatus
from ..money import MoneyError, parse_money_to_minor

DEFAULT_BUSINESS_TZ = "Asia/Kolkata"


class RejectionError(Exception):
    """A row that cannot be trusted, with everything the report needs."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        column: str | None = None,
        value: object = None,
    ) -> None:
        self.code = code
        self.column = column
        self.value = None if value is None else str(value)[:200]
        super().__init__(message)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "error_code": self.code,
            "error_message": str(self),
            "column_name": self.column,
            "raw_value": self.value,
        }


class Normalizer(Protocol):
    """What every per-source normaliser provides."""

    dataset: str
    source_system: SourceSystem
    entity_types: tuple[EntityType, ...]
    required_columns: tuple[str, ...]

    def normalise(
        self, row: Mapping[str, str], *, business_timezone: str = DEFAULT_BUSINESS_TZ
    ) -> CanonicalTransaction: ...


# --------------------------------------------------------------------------
# Field access
# --------------------------------------------------------------------------

def require(row: Mapping[str, str], column: str) -> str:
    """Fetch a column that must be present and non-empty."""
    if column not in row:
        raise RejectionError(
            "MISSING_COLUMN", f"required column {column!r} is absent", column=column
        )
    value = (row[column] or "").strip()
    if not value:
        raise RejectionError(
            "MISSING_FIELD", f"{column!r} is required but empty", column=column, value=row[column]
        )
    return value


def optional(row: Mapping[str, str], column: str) -> str | None:
    """Fetch a column that may be absent or blank. Blank becomes None.

    Blank is meaningfully different from absent-and-required: a settlement
    export with no UTR is the `missing_bank_credit` case, which the engine
    must see as a real record with a gap, not as a rejected row.
    """
    value = (row.get(column) or "").strip()
    return value or None


def money(
    row: Mapping[str, str], column: str, *, currency: str, allow_negative: bool = False
) -> int:
    """Parse a money column into minor units, re-raising as a rejection.

    `money.py` already refuses floats, excess precision, and ambiguous
    grouping. This only translates its `MoneyError` into the rejection
    shape so the column name travels with it.
    """
    raw = row.get(column)
    if raw is None:
        raise RejectionError(
            "MISSING_COLUMN", f"required column {column!r} is absent", column=column
        )
    try:
        return parse_money_to_minor(raw, currency=currency, allow_negative=allow_negative)
    except MoneyError as exc:
        raise RejectionError(exc.code, str(exc), column=column, value=raw) from exc


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

#: Accepted input shapes, most specific first. Deliberately a closed list:
#: guessing at an unrecognised format is how a date silently lands in the
#: wrong year.
_DATE_ONLY_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
_DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
)


def parse_instant(
    raw: str, *, column: str, business_timezone: str
) -> tuple[datetime, date, bool]:
    """Parse a source timestamp into (UTC instant, business date, tz_assumed).

    Three cases, and the third is the one that matters:

    * an offset-bearing timestamp is authoritative;
    * a date-only value (how bank statements export) is anchored at
      midnight in the business timezone, and flagged assumed;
    * a naive datetime is interpreted in the business timezone, and
      flagged assumed - PRD 6.2 requires that assumption be recorded on
      the record rather than made silently.

    The business date is always computed in the business timezone, which
    is what makes a 23:58 IST capture settle on the following business
    day rather than appearing to settle instantly.
    """
    text = (raw or "").strip()
    if not text:
        raise RejectionError(
            "MISSING_FIELD", f"{column!r} is required but empty", column=column, value=raw
        )

    tz = _zone(business_timezone, column=column)

    # 1. Offset-aware ISO-8601.
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None

    if parsed is not None and parsed.tzinfo is not None:
        utc = parsed.astimezone(_UTC)
        return utc, utc.astimezone(tz).date(), False

    # 2. Date-only.
    for fmt in _DATE_ONLY_FORMATS:
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        local = naive.replace(tzinfo=tz)
        return local.astimezone(_UTC), local.date(), True

    # 3. Naive datetime, including the ISO one parsed above without an offset.
    candidates = [parsed] if parsed is not None else []
    for fmt in _DATETIME_FORMATS:
        try:
            candidates.append(datetime.strptime(text, fmt))
            break
        except ValueError:
            continue

    for naive in candidates:
        if naive is None:
            continue
        local = naive.replace(tzinfo=tz)
        return local.astimezone(_UTC), local.date(), True

    raise RejectionError(
        "INVALID_DATE",
        f"{column!r} is not a recognised date or timestamp format",
        column=column,
        value=raw,
    )


def _zone(name: str, *, column: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:  # noqa: BLE001 - surfaced as a rejection
        raise RejectionError(
            "INVALID_TIMEZONE", f"unknown timezone {name!r}", column=column, value=name
        ) from exc


_UTC = ZoneInfo("UTC")


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------

#: UTR / RRN / NEFT reference shapes seen in Indian bank narrations. The
#: patterns are anchored to a token boundary rather than searching loosely,
#: because a substring match against free text is how a wrong reference
#: gets attached with false confidence.
_REFERENCE_PATTERNS = (
    re.compile(r"\b(UTR[0-9]{4,})\b", re.IGNORECASE),
    re.compile(r"\b([0-9]{12,22})\b"),                      # bare UTR/RRN digits
    re.compile(r"\b(setl_[A-Za-z0-9_]{4,})\b"),             # our own settlement ids
    re.compile(r"\b(pay_[A-Za-z0-9]{6,})\b"),
)


def extract_reference(*sources: str | None) -> str | None:
    """Pull the first plausible reference out of narration text.

    Returns the reference *as found*, uppercased. Deliberately returns at
    most one: a narration containing two candidate references is
    ambiguous, and the matching engine should see the first-and-strongest
    rather than a set it has to disambiguate downstream.

    A truncated reference still returns - `UTR7739` from a cut-off
    narration is a usable prefix. What it must never do is let a prefix
    match *alone* resolve a case; that corroboration requirement lives in
    the matching rules, not here.
    """
    for source in sources:
        if not source:
            continue
        for pattern in _REFERENCE_PATTERNS:
            found = pattern.search(source)
            if found:
                return found.group(1).upper()
    return None


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

def map_status(
    raw: str, mapping: Mapping[str, TxnStatus], *, column: str = "status"
) -> TxnStatus:
    """Map a source status into the controlled vocabulary.

    An unrecognised status is a rejection, never a default. Silently
    coercing an unknown status to `pending` would let a genuinely new
    source state pass through as something the engine thinks it
    understands.
    """
    key = (raw or "").strip().lower()
    if not key:
        raise RejectionError(
            "MISSING_FIELD", f"{column!r} is required but empty", column=column, value=raw
        )
    try:
        return mapping[key]
    except KeyError:
        raise RejectionError(
            "UNKNOWN_STATUS",
            f"{raw!r} is not a recognised value for {column!r}; "
            f"known values are {sorted(mapping)}",
            column=column,
            value=raw,
        ) from None


def build(**kwargs) -> CanonicalTransaction:
    """Construct a CanonicalTransaction, translating invariant failures.

    The dataclass enforces the same identities the database does. When one
    trips during normalisation it is a bad *row*, so it surfaces as a
    rejection with the code intact rather than as an unhandled exception.
    """
    try:
        return CanonicalTransaction(**kwargs)
    except CanonicalError as exc:
        raise RejectionError(exc.code, str(exc)) from exc
