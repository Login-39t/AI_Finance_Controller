"""Money. The first file in this project, because everything else assumes it.

One rule underwrites the whole system: money is an ``int`` of minor units
(paise for INR) and nothing else. There is no float path in, no float path
out, and no silent rounding anywhere between.

Three things this module refuses to do, on purpose:

* accept a ``float`` - ``0.1 + 0.2`` is not ``0.3`` and a reconciliation
  engine that tolerates that is worthless;
* round a value with more precision than the currency has - ``"100.005"``
  is a data error in the source system, not a number to be helpfully
  rounded to ``100.01``;
* infer sign from an amount when the source also carries a direction -
  two sources of truth for a sign means one of them is wrong.

Every rejection carries a stable ``code``. Those codes are what the import
rejection report shows the user, so they are part of the public contract.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

__all__ = [
    "MoneyError",
    "Direction",
    "CURRENCY_EXPONENT",
    "parse_money_to_minor",
    "minor_to_decimal",
    "format_minor",
    "split_sign",
    "apply_direction",
    "allocate_minor",
]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class MoneyError(ValueError):
    """A money value that cannot be trusted.

    Carries a stable machine code so the import rejection report and the
    API error body can both key off it without parsing English.
    """

    def __init__(self, code: str, message: str, *, value: object = None) -> None:
        self.code = code
        self.value = value
        super().__init__(message)


Direction = Literal["credit", "debit"]


# --------------------------------------------------------------------------
# Currency
# --------------------------------------------------------------------------

# ISO 4217 minor-unit exponents. Deliberately a short table rather than a
# dependency: the MVP is INR-only, and an unknown currency must fail loudly
# rather than silently assume two decimals.
CURRENCY_EXPONENT: Final[dict[str, int]] = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AED": 2,
    "SGD": 2,
    "JPY": 0,   # no minor unit
    "KWD": 3,   # three, not two
    "BHD": 3,
    "OMR": 3,
}

CURRENCY_SYMBOL: Final[dict[str, str]] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}

# Postgres BIGINT. A value outside this range is a parsing error, not a
# number we will try to store.
_INT64_MIN: Final[int] = -(2 ** 63)
_INT64_MAX: Final[int] = 2 ** 63 - 1


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

# Currency noise that appears in real CSV exports.
_PREFIX_NOISE = re.compile(
    r"^(?:₹|rs\.?|inr|usd|\$|eur|€|gbp|£)\s*",
    re.IGNORECASE,
)
# "1,234.56 CR" / "500.00 DR" - common in bank statement exports.
_SUFFIX_MARKER = re.compile(r"\s*(cr|dr)\.?$", re.IGNORECASE)

# Grouping patterns. A separator is only stripped when the grouping is a
# recognised system; "1,2 34.00" and "12,34,5.6" are malformed, not
# creatively formatted.
_PLAIN = re.compile(r"^\d+(?:\.\d+)?$")
_WESTERN = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_INDIAN = re.compile(r"^\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?$")


def parse_money_to_minor(
    value: object,
    *,
    currency: str = "INR",
    allow_negative: bool = True,
) -> int:
    """Parse a source amount into signed minor units.

    ``value`` is a *major* unit amount as it appeared in the source file:
    ``"1,23,456.78"``, ``"-500.00"``, ``"(42.50)"``, ``Decimal("99.99")``.
    An ``int`` is accepted and read as whole major units.

    A ``float`` is rejected. That is not pedantry: by the time a float
    reaches this function the precision is already gone, and there is no
    way to tell ``1234.56`` from ``1234.5599999999999`` after the fact.

    Raises:
        MoneyError: with a stable ``code``, never a bare ValueError.
    """
    exponent = _exponent_for(currency)

    # bool is an int subclass, and True would otherwise parse as 1.
    if isinstance(value, bool):
        raise MoneyError("AMOUNT_MALFORMED", "boolean is not an amount", value=value)

    if isinstance(value, float):
        raise MoneyError(
            "AMOUNT_IS_FLOAT",
            "float amounts are rejected: pass the original string or a Decimal",
            value=value,
        )

    if isinstance(value, int):
        dec = Decimal(value)
        negative = dec < 0
    elif isinstance(value, Decimal):
        dec = value
        negative = dec < 0
    elif isinstance(value, str):
        dec, negative = _parse_string(value)
    elif value is None:
        raise MoneyError("AMOUNT_MISSING", "amount is required", value=value)
    else:
        raise MoneyError(
            "AMOUNT_MALFORMED",
            f"unsupported amount type {type(value).__name__}",
            value=value,
        )

    if negative and not allow_negative:
        raise MoneyError(
            "AMOUNT_NEGATIVE",
            "a negative amount is not permitted here: sign belongs to the direction field",
            value=value,
        )

    minor = _to_minor(dec, exponent, original=value)

    if not (_INT64_MIN <= minor <= _INT64_MAX):
        raise MoneyError("AMOUNT_OUT_OF_RANGE", "amount exceeds 64-bit range", value=value)

    return minor


def _parse_string(raw: str) -> tuple[Decimal, bool]:
    """Normalise a source string into a Decimal plus an explicit sign."""
    text = raw.strip()
    if not text:
        raise MoneyError("AMOUNT_EMPTY", "amount is empty", value=raw)

    # Normalise unicode minus and non-breaking spaces before anything else.
    text = text.replace("−", "-").replace(" ", " ").replace(" ", " ")

    negative = False

    # Accounting parentheses: (1,234.56) means -1234.56
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    text = _PREFIX_NOISE.sub("", text).strip()

    # CR / DR markers. DR is a debit; we record the magnitude and let the
    # caller's direction field own the sign, so a DR marker alone does not
    # flip it - it is corroborating metadata, not a sign source.
    text = _SUFFIX_MARKER.sub("", text).strip()

    if text.startswith(("-", "+")):
        if text[0] == "-":
            if negative:
                raise MoneyError(
                    "AMBIGUOUS_SIGN",
                    "amount is negated twice (parentheses and a minus sign)",
                    value=raw,
                )
            negative = True
        text = text[1:].strip()

    # Re-strip currency noise: "-Rs. 500" puts the symbol after the sign.
    text = _PREFIX_NOISE.sub("", text).strip()

    if not text:
        raise MoneyError("AMOUNT_EMPTY", "amount has no digits", value=raw)

    # Internal whitespace is never valid at this point. Stripping it here
    # would turn the corrupt export "1,2 34.00" into a well-formed
    # "1,234.00" and quietly invent a number - the exact silent coercion
    # this module exists to prevent. Some European exports use a space as
    # a thousands separator; that is ambiguous against this case, so it is
    # rejected rather than guessed at.
    if any(ch.isspace() for ch in text):
        raise MoneyError(
            "AMOUNT_MALFORMED",
            "amount contains whitespace between digits",
            value=raw,
        )

    if "," in text:
        if _WESTERN.fullmatch(text) or _INDIAN.fullmatch(text):
            text = text.replace(",", "")
        else:
            raise MoneyError(
                "AMOUNT_MALFORMED",
                "digit grouping is not a recognised Indian or Western pattern",
                value=raw,
            )
    elif not _PLAIN.fullmatch(text):
        raise MoneyError("AMOUNT_MALFORMED", "amount is not a plain decimal number", value=raw)

    try:
        dec = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - regex should prevent this
        raise MoneyError("AMOUNT_MALFORMED", "amount is not a decimal number", value=raw) from exc

    return (-dec if negative else dec), negative


def _to_minor(dec: Decimal, exponent: int, *, original: object) -> int:
    """Scale a Decimal to minor units, refusing to discard precision."""
    if not dec.is_finite():
        raise MoneyError("AMOUNT_MALFORMED", "amount is not finite", value=original)

    scaled = dec.scaleb(exponent)

    # scaled must already be a whole number. If it is not, the source
    # carried more precision than the currency has, and rounding it would
    # invent money.
    if scaled != scaled.to_integral_value():
        raise MoneyError(
            "AMOUNT_PRECISION_LOSS",
            f"amount has more than {exponent} decimal places and cannot be stored exactly",
            value=original,
        )

    return int(scaled)


def _exponent_for(currency: str) -> int:
    code = (currency or "").strip().upper()
    try:
        return CURRENCY_EXPONENT[code]
    except KeyError:
        raise MoneyError(
            "AMOUNT_UNSUPPORTED_CURRENCY",
            f"no minor-unit exponent is known for currency {code!r}",
            value=currency,
        ) from None


# --------------------------------------------------------------------------
# Sign and direction
# --------------------------------------------------------------------------

def split_sign(minor: int) -> tuple[int, Direction]:
    """Split a signed minor amount into magnitude plus direction.

    The database stores non-negative amounts and puts the sign in
    ``direction``, so exactly one column carries it.
    """
    return (abs(minor), "debit" if minor < 0 else "credit")


def apply_direction(minor_abs: int, direction: Direction) -> int:
    """Re-apply a stored direction to a magnitude, for display or arithmetic."""
    if minor_abs < 0:
        raise MoneyError("AMOUNT_NEGATIVE", "magnitude must be non-negative", value=minor_abs)
    return -minor_abs if direction == "debit" else minor_abs


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def minor_to_decimal(minor: int, currency: str = "INR") -> Decimal:
    """Exact Decimal in major units. For display and reports only.

    Never feed the result back into a calculation that lands in the
    database - reconciliation arithmetic stays in integer minor units.
    """
    if isinstance(minor, bool) or not isinstance(minor, int):
        raise MoneyError("AMOUNT_MALFORMED", "minor units must be an int", value=minor)
    return Decimal(minor).scaleb(-_exponent_for(currency))


def format_minor(
    minor: int,
    currency: str = "INR",
    *,
    symbol: bool = True,
    grouping: Literal["auto", "indian", "western"] = "auto",
) -> str:
    """Render minor units for a human.

    INR defaults to Indian grouping (``1,23,456.78``) because that is what
    an Indian finance team reads without translating in their head.
    """
    exponent = _exponent_for(currency)
    if isinstance(minor, bool) or not isinstance(minor, int):
        raise MoneyError("AMOUNT_MALFORMED", "minor units must be an int", value=minor)

    negative = minor < 0
    digits = str(abs(minor)).rjust(exponent + 1, "0")
    whole, frac = (digits[:-exponent], digits[-exponent:]) if exponent else (digits, "")

    style = grouping
    if style == "auto":
        style = "indian" if currency.upper() == "INR" else "western"

    grouped = _group_indian(whole) if style == "indian" else _group_western(whole)

    out = f"{grouped}.{frac}" if frac else grouped
    if symbol:
        out = f"{CURRENCY_SYMBOL.get(currency.upper(), currency.upper() + ' ')}{out}"
    return f"-{out}" if negative else out


def _group_western(whole: str) -> str:
    return f"{int(whole):,}"


def _group_indian(whole: str) -> str:
    """Last three digits, then pairs: 12345678 -> 1,23,45,678."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


# --------------------------------------------------------------------------
# Allocation
# --------------------------------------------------------------------------

def allocate_minor(total_minor: int, weights: list[int]) -> list[int]:
    """Split an amount across weights without losing or inventing a paise.

    Used for split allocation, where one payment is apportioned across
    several ledger postings. The guarantee that matters is
    ``sum(result) == total_minor``, exactly, always - the database enforces
    the same identity with a constraint trigger, and this is the function
    that has to satisfy it.

    Remainder paise go to the largest weights first (largest-remainder
    method), so the distribution is deterministic and reproducible rather
    than dependent on dict ordering.
    """
    if not weights:
        raise MoneyError("ALLOCATION_EMPTY", "cannot allocate across zero weights")
    if any(w < 0 for w in weights):
        raise MoneyError("ALLOCATION_NEGATIVE_WEIGHT", "allocation weights must be non-negative")

    total_weight = sum(weights)
    if total_weight == 0:
        raise MoneyError("ALLOCATION_ZERO_WEIGHT", "allocation weights sum to zero")

    sign = -1 if total_minor < 0 else 1
    magnitude = abs(total_minor)

    floors: list[int] = []
    remainders: list[tuple[int, int]] = []   # (remainder numerator, index)
    for i, w in enumerate(weights):
        product = magnitude * w
        floors.append(product // total_weight)
        remainders.append((product % total_weight, i))

    shortfall = magnitude - sum(floors)
    # Largest remainder first; ties broken by index so the result is stable.
    remainders.sort(key=lambda pair: (-pair[0], pair[1]))
    for _, idx in remainders[:shortfall]:
        floors[idx] += 1

    return [sign * amount for amount in floors]
