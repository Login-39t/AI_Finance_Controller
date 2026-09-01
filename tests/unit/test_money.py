"""Tests for the money layer.

Every case in PRD section 6.1 has a test here. If one of these fails, the
system's central correctness claim is false, so this file gates everything.
"""

from decimal import Decimal

import pytest
from ledgergraph_domain.money import (
    MoneyError,
    allocate_minor,
    apply_direction,
    format_minor,
    minor_to_decimal,
    parse_money_to_minor,
    split_sign,
)

# --------------------------------------------------------------------------
# Parsing: the happy paths
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("0.00", 0),
        ("1", 100),
        ("1.5", 150),
        ("1.50", 150),
        ("1234.56", 123456),
        ("1,234.56", 123456),           # western grouping
        ("1,23,456.78", 12345678),      # indian grouping
        ("12,34,56,789.00", 123456789_00),
        ("999999999.99", 99999999999),
        ("₹1,234.56", 123456),
        ("Rs. 1,234.56", 123456),
        ("Rs.1234.56", 123456),
        ("INR 500.00", 50000),
        ("  42.00  ", 4200),
        ("1234.56 CR", 123456),         # bank statement marker
        ("500.00 DR", 50000),           # magnitude only; direction owns the sign
    ],
)
def test_parses_real_world_strings(raw, expected):
    assert parse_money_to_minor(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-500.00", -50000),
        ("(1,234.56)", -123456),        # accounting parentheses
        ("−250.00", -25000),            # unicode minus U+2212
        ("-Rs. 500", -50000),           # symbol after the sign
    ],
)
def test_parses_negatives(raw, expected):
    assert parse_money_to_minor(raw) == expected


def test_accepts_decimal_and_int_as_major_units():
    assert parse_money_to_minor(Decimal("1234.56")) == 123456
    assert parse_money_to_minor(Decimal("0.01")) == 1
    assert parse_money_to_minor(500) == 50000
    assert parse_money_to_minor(0) == 0


# --------------------------------------------------------------------------
# Parsing: the refusals. These are the point of the module.
# --------------------------------------------------------------------------

def test_float_is_rejected_outright():
    """The headline rule. A float has already lost the precision."""
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor(1234.56)
    assert exc.value.code == "AMOUNT_IS_FLOAT"


def test_float_rejection_covers_the_classic_case():
    # 0.1 + 0.2 == 0.30000000000000004
    with pytest.raises(MoneyError):
        parse_money_to_minor(0.1 + 0.2)


def test_bool_is_not_an_amount():
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor(True)
    assert exc.value.code == "AMOUNT_MALFORMED"


@pytest.mark.parametrize("raw", ["100.005", "1.239", "0.001"])
def test_excess_precision_is_rejected_not_rounded(raw):
    """PRD 6.1: reject with AMOUNT_PRECISION_LOSS. Do not round silently."""
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor(raw)
    assert exc.value.code == "AMOUNT_PRECISION_LOSS"


@pytest.mark.parametrize(
    "raw",
    [
        "1,2 34.00",     # the PRD's example of a broken bank export
        "12,34,5.6",     # grouping that matches neither system
        "1,0000.00",     # four digits in a western group
        "abc",
        "1.2.3",
        "12,,345.00",
        "--500",
        "1e5",           # scientific notation is not an accounting format
    ],
)
def test_malformed_strings_are_rejected(raw):
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor(raw)
    assert exc.value.code == "AMOUNT_MALFORMED"


@pytest.mark.parametrize("raw", ["", "   ", "₹", "Rs."])
def test_empty_is_rejected(raw):
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor(raw)
    assert exc.value.code == "AMOUNT_EMPTY"


def test_none_is_missing_not_zero():
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor(None)
    assert exc.value.code == "AMOUNT_MISSING"


def test_double_negation_is_ambiguous():
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor("(-500.00)")
    assert exc.value.code == "AMBIGUOUS_SIGN"


def test_negative_rejected_where_direction_owns_the_sign():
    """canonical_transactions.gross_amount_minor has CHECK (>= 0)."""
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor("-500.00", allow_negative=False)
    assert exc.value.code == "AMOUNT_NEGATIVE"


def test_unknown_currency_fails_loudly():
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor("100.00", currency="XYZ")
    assert exc.value.code == "AMOUNT_UNSUPPORTED_CURRENCY"


def test_amount_beyond_int64_is_rejected():
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor("9" * 20)
    assert exc.value.code == "AMOUNT_OUT_OF_RANGE"


# --------------------------------------------------------------------------
# Currencies with a different exponent
# --------------------------------------------------------------------------

def test_zero_exponent_currency():
    assert parse_money_to_minor("500", currency="JPY") == 500
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor("500.50", currency="JPY")
    assert exc.value.code == "AMOUNT_PRECISION_LOSS"


def test_three_exponent_currency():
    assert parse_money_to_minor("1.234", currency="KWD") == 1234
    with pytest.raises(MoneyError) as exc:
        parse_money_to_minor("1.2345", currency="KWD")
    assert exc.value.code == "AMOUNT_PRECISION_LOSS"


# --------------------------------------------------------------------------
# Sign and direction
# --------------------------------------------------------------------------

def test_split_and_reapply_direction_round_trips():
    for signed in (-123456, 0, 123456):
        magnitude, direction = split_sign(signed)
        assert magnitude >= 0
        assert apply_direction(magnitude, direction) == signed


def test_zero_is_a_credit_by_convention():
    assert split_sign(0) == (0, "credit")


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("minor", "expected"),
    [
        (0, "₹0.00"),
        (1, "₹0.01"),
        (99, "₹0.99"),
        (100, "₹1.00"),
        (123456, "₹1,234.56"),
        (12345678, "₹1,23,456.78"),        # lakh
        (12345678900, "₹12,34,56,789.00"),  # crore
        (-123456, "-₹1,234.56"),
    ],
)
def test_inr_uses_indian_grouping(minor, expected):
    assert format_minor(minor) == expected


def test_non_inr_uses_western_grouping():
    assert format_minor(12345678, "USD") == "$123,456.78"


def test_grouping_can_be_forced():
    assert format_minor(12345678, "INR", grouping="western") == "₹123,456.78"


def test_format_without_symbol():
    assert format_minor(123456, symbol=False) == "1,234.56"


def test_zero_exponent_currency_formats_without_decimals():
    assert format_minor(500, "JPY", symbol=False) == "500"


def test_format_rejects_non_int():
    with pytest.raises(MoneyError):
        format_minor(1234.56)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Round trips
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    ["0.00", "0.01", "1.00", "1234.56", "1,23,456.78", "99999999.99", "-4200.00"],
)
def test_parse_format_parse_is_identity(raw):
    minor = parse_money_to_minor(raw)
    assert parse_money_to_minor(format_minor(minor, symbol=False)) == minor


def test_minor_to_decimal_is_exact():
    assert minor_to_decimal(123456) == Decimal("1234.56")
    assert minor_to_decimal(1) == Decimal("0.01")
    assert minor_to_decimal(500, "JPY") == Decimal("500")


# --------------------------------------------------------------------------
# Allocation: the split-allocation constraint trigger depends on this
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("total", "weights"),
    [
        (10000, [1, 1, 1]),          # 100.00 across thirds: the classic
        (100, [1, 1, 1]),            # 1.00 across thirds
        (1, [1, 1, 1]),              # one paise across three
        (0, [1, 1, 1]),
        (123456, [7, 2, 1]),
        (-10000, [1, 1, 1]),         # negatives conserve too
        (999, [1, 1, 1, 1, 1, 1, 1]),
    ],
)
def test_allocation_conserves_every_paise(total, weights):
    parts = allocate_minor(total, weights)
    assert sum(parts) == total
    assert len(parts) == len(weights)


def test_allocation_is_deterministic():
    a = allocate_minor(10000, [1, 1, 1])
    b = allocate_minor(10000, [1, 1, 1])
    assert a == b == [3334, 3333, 3333]


def test_allocation_respects_weights():
    assert allocate_minor(10000, [3, 1]) == [7500, 2500]


def test_allocation_tolerates_zero_weights():
    parts = allocate_minor(10000, [1, 0, 1])
    assert sum(parts) == 10000
    assert parts[1] == 0


@pytest.mark.parametrize(
    ("weights", "code"),
    [
        ([], "ALLOCATION_EMPTY"),
        ([0, 0], "ALLOCATION_ZERO_WEIGHT"),
        ([1, -1], "ALLOCATION_NEGATIVE_WEIGHT"),
    ],
)
def test_allocation_rejects_bad_weights(weights, code):
    with pytest.raises(MoneyError) as exc:
        allocate_minor(10000, weights)
    assert exc.value.code == code


# --------------------------------------------------------------------------
# The settlement identity, which the DB also enforces as a CHECK
# --------------------------------------------------------------------------

def test_settlement_identity_holds_in_integers():
    """gross - fee - tax = net, exactly, with a realistic 2% + 18% GST fee."""
    gross = parse_money_to_minor("10,000.00")          # 10,00,000 paise
    fee = gross * 200 // 10_000                         # 2.00% -> 20,000 paise
    tax = fee * 1800 // 10_000                          # 18% GST -> 3,600 paise
    net = gross - fee - tax

    assert fee == 20000
    assert tax == 3600
    assert net == 976400
    assert format_minor(net) == "₹9,764.00"
    assert net == gross - fee - tax
