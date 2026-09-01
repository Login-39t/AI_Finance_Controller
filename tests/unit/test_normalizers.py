"""Normalisation: source rows to canonical transactions.

Two layers of testing here, deliberately.

*Hand-built rows* pin the specific behaviours - a naive timestamp being
flagged, a signed bank amount being rejected, a truncated UTR still being
extracted. Those are the cases from PRD section 6 that must not regress.

*The real generated dataset* then runs every normaliser over every row of
the actual CSVs. That catches the class of bug a hand-written fixture
never will: a column the generator emits that the normaliser does not
expect, or vice versa. The two halves of this project were written days
apart, and this is what proves they still fit together.
"""

from __future__ import annotations

import csv
import random
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import EntityType, SourceSystem, TxnDirection, TxnStatus
from ledgergraph_domain.normalizers import (
    NORMALIZERS,
    RejectionError,
    extract_reference,
    get_normalizer,
)
from ledgergraph_domain.normalizers.base import parse_instant

from data.synthetic.anomalies import inject_anomalies
from data.synthetic.generator import generate_world, write_world

IST = "Asia/Kolkata"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

def test_every_dataset_the_generator_writes_has_a_normalizer():
    """The generator and the normalisers must cover the same six datasets."""
    expected = {
        "payments", "settlement_batches", "settlement_lines",
        "bank_statement", "invoices", "ledger",
    }
    assert set(NORMALIZERS) == expected


def test_unknown_dataset_is_rejected_not_defaulted():
    with pytest.raises(RejectionError) as exc:
        get_normalizer("not_a_dataset")
    assert exc.value.code == "UNKNOWN_DATASET"


# --------------------------------------------------------------------------
# Timestamps - PRD section 6.2
# --------------------------------------------------------------------------

def test_offset_bearing_timestamp_is_authoritative():
    utc, business, assumed = parse_instant(
        "2026-03-04T11:42:00+05:30", column="t", business_timezone=IST
    )
    assert utc == datetime(2026, 3, 4, 6, 12, tzinfo=UTC)
    assert business == date(2026, 3, 4)
    assert assumed is False


def test_naive_timestamp_is_interpreted_in_business_tz_and_flagged():
    utc, business, assumed = parse_instant(
        "2026-03-04T11:42:00", column="t", business_timezone=IST
    )
    assert utc == datetime(2026, 3, 4, 6, 12, tzinfo=UTC)
    assert business == date(2026, 3, 4)
    assert assumed is True, "an assumed timezone must be recorded, not applied silently"


def test_date_only_is_anchored_at_local_midnight_and_flagged():
    """How every bank statement exports. Anchoring in UTC instead would
    shift the business date at the boundary."""
    utc, business, assumed = parse_instant("2026-03-04", column="t", business_timezone=IST)
    assert business == date(2026, 3, 4)
    assert assumed is True
    assert utc == datetime(2026, 3, 3, 18, 30, tzinfo=UTC)


def test_late_night_capture_keeps_its_own_business_date():
    """23:58 IST is still that day's business date. Comparing raw UTC
    instants would move it to the next day and make the settlement look
    a day faster than it was."""
    _, business, _ = parse_instant(
        "2026-03-04T23:58:00+05:30", column="t", business_timezone=IST
    )
    assert business == date(2026, 3, 4)


@pytest.mark.parametrize("raw", ["", "   ", "not-a-date", "2026-13-45", "04/03/26 xyz"])
def test_unparseable_dates_are_rejected(raw):
    with pytest.raises(RejectionError) as exc:
        parse_instant(raw, column="created_at", business_timezone=IST)
    assert exc.value.code in ("INVALID_DATE", "MISSING_FIELD")
    assert exc.value.column == "created_at"


# --------------------------------------------------------------------------
# Reference extraction - PRD section 6.3
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("narration", "expected"),
    [
        ("NEFT CR-RAZORPAY SOFTWARE PVT LT-UTR773941", "UTR773941"),
        ("NEFT CR-RAZORPAY SOFTWARE-UTR7739", "UTR7739"),      # truncated, still usable
        ("IMPS/123456789012/RAZORPAY", "123456789012"),
        ("settlement setl_20260304 payout", "SETL_20260304"),
        ("NEFT CR-RAZORPAY SOFTWARE PVT LTD", None),           # no reference at all
        ("", None),
        (None, None),
    ],
)
def test_reference_extraction(narration, expected):
    assert extract_reference(narration) == expected


def test_stated_reference_column_wins_over_narration():
    """A dedicated field is stronger evidence than text scraped from prose."""
    n = get_normalizer("bank_statement")
    txn = n.normalise(
        {
            "bank_txn_id": "BNK1", "date": "2026-03-04", "amount": "100.00",
            "direction": "credit", "reference": "UTR111111",
            "description": "NEFT CR-SOMETHING-UTR999999",
        },
        business_timezone=IST,
    )
    assert txn.reference_id == "UTR111111"
    assert "reference_extracted_from_narration" not in txn.data_quality_flags


def test_reference_recovered_from_narration_is_flagged_as_weaker():
    n = get_normalizer("bank_statement")
    txn = n.normalise(
        {
            "bank_txn_id": "BNK1", "date": "2026-03-04", "amount": "100.00",
            "direction": "credit", "reference": "",
            "description": "NEFT CR-RAZORPAY-UTR773941",
        },
        business_timezone=IST,
    )
    assert txn.reference_id == "UTR773941"
    assert "reference_extracted_from_narration" in txn.data_quality_flags


# --------------------------------------------------------------------------
# Sign and direction
# --------------------------------------------------------------------------

def test_bank_row_with_both_a_sign_and_a_direction_is_rejected():
    """Exactly one field may carry the sign. Two is ambiguous, and
    guessing produces a plausible wrong number."""
    n = get_normalizer("bank_statement")
    with pytest.raises(RejectionError) as exc:
        n.normalise(
            {"bank_txn_id": "B1", "date": "2026-03-04",
             "amount": "-100.00", "direction": "credit"},
            business_timezone=IST,
        )
    assert exc.value.code == "AMBIGUOUS_SIGN"


def test_double_sided_ledger_line_is_rejected_not_netted():
    n = get_normalizer("ledger")
    with pytest.raises(RejectionError) as exc:
        n.normalise(
            {"journal_id": "J1", "account": "1010-Bank", "debit": "500.00",
             "credit": "300.00", "posted_at": "2026-03-04", "reference": "setl_1"},
            business_timezone=IST,
        )
    assert exc.value.code == "AMBIGUOUS_SIGN"


def test_refund_is_a_debit():
    n = get_normalizer("payments")
    txn = n.normalise(
        {"payment_id": "rfnd_1", "order_id": "order_1", "amount": "100.00",
         "currency": "INR", "status": "refunded", "created_at": "2026-03-04T10:00:00+05:30",
         "record_type": "refund", "parent_payment_id": "pay_1"},
        business_timezone=IST,
    )
    assert txn.entity_type is EntityType.REFUND
    assert txn.direction is TxnDirection.DEBIT
    assert txn.parent_external_id == "pay_1"
    assert txn.signed_net_minor == -10000


def test_refund_without_a_parent_id_is_rejected():
    n = get_normalizer("payments")
    with pytest.raises(RejectionError) as exc:
        n.normalise(
            {"payment_id": "rfnd_1", "order_id": "o1", "amount": "100.00",
             "currency": "INR", "status": "refunded",
             "created_at": "2026-03-04T10:00:00+05:30",
             "record_type": "refund", "parent_payment_id": ""},
            business_timezone=IST,
        )
    assert exc.value.code == "MISSING_FIELD"


# --------------------------------------------------------------------------
# Status vocabulary
# --------------------------------------------------------------------------

def test_unknown_status_is_rejected_not_defaulted():
    """Coercing an unrecognised status to `pending` would let a genuinely
    new source state pass as one the engine thinks it understands."""
    n = get_normalizer("payments")
    with pytest.raises(RejectionError) as exc:
        n.normalise(
            {"payment_id": "p1", "order_id": "o1", "amount": "100.00", "currency": "INR",
             "status": "quantum_superposition", "created_at": "2026-03-04T10:00:00+05:30"},
            business_timezone=IST,
        )
    assert exc.value.code == "UNKNOWN_STATUS"
    assert exc.value.column == "status"


# --------------------------------------------------------------------------
# Missing UTR: a flag, not a rejection
# --------------------------------------------------------------------------

def test_settlement_without_a_utr_is_kept_and_flagged():
    """This is the missing_bank_credit case. Rejecting it would delete the
    exception the system exists to surface."""
    n = get_normalizer("settlement_batches")
    txn = n.normalise(
        {"batch_id": "setl_20260304", "gross": "1000.00", "fee": "20.00", "tax": "3.60",
         "net": "976.40", "status": "settled", "settled_at": "2026-03-04T05:30:00+05:30",
         "payout_utr": ""},
        business_timezone=IST,
    )
    assert txn.reference_id is None
    assert "settlement_utr_missing" in txn.data_quality_flags


# --------------------------------------------------------------------------
# The amount identity
# --------------------------------------------------------------------------

def test_settlement_whose_components_do_not_balance_is_rejected():
    n = get_normalizer("settlement_batches")
    with pytest.raises(RejectionError) as exc:
        n.normalise(
            {"batch_id": "setl_1", "gross": "1000.00", "fee": "20.00", "tax": "3.60",
             "net": "999.00",  # wrong on purpose
             "status": "settled", "settled_at": "2026-03-04", "payout_utr": "UTR1"},
            business_timezone=IST,
        )
    assert exc.value.code == "AMOUNT_IDENTITY_VIOLATION"


def test_non_settlement_entity_may_not_carry_a_fee():
    """Mirrors the ck_canon_fee_scope CHECK. A bank transaction with a fee
    is a normalisation bug, not a real record."""
    from ledgergraph_domain.canonical import CanonicalError

    with pytest.raises(CanonicalError) as exc:
        CanonicalTransaction(
            source_system=SourceSystem.BANK_STATEMENT,
            entity_type=EntityType.BANK_TRANSACTION,
            external_id="B1", currency="INR",
            gross_amount_minor=1000, fee_amount_minor=100, tax_amount_minor=0,
            net_amount_minor=900,
            direction=TxnDirection.CREDIT, status=TxnStatus.POSTED,
            event_at=datetime(2026, 3, 4, tzinfo=UTC),
            business_date=date(2026, 3, 4),
        )
    assert exc.value.code == "FEE_OUT_OF_SCOPE"


def test_external_id_norm_is_derived_for_indexed_joins():
    n = get_normalizer("payments")
    txn = n.normalise(
        {"payment_id": "  pay_AbC123  ", "order_id": "o1", "amount": "1.00",
         "currency": "INR", "status": "captured",
         "created_at": "2026-03-04T10:00:00+05:30"},
        business_timezone=IST,
    )
    assert txn.external_id == "pay_AbC123", "the original must survive for display and audit"
    assert txn.external_id_norm == "PAY_ABC123"


# --------------------------------------------------------------------------
# Against the real generated dataset
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    """A real dataset, written to disk exactly as `make gen-data` would."""
    out = tmp_path_factory.mktemp("synthetic")
    world = generate_world(200, seed=11, lookback_days=30)
    inject_anomalies(world, random.Random(11 ^ 0x5EED))
    write_world(world, out)
    return out


DATASET_FILES = {
    "payments": "payments.csv",
    "settlement_batches": "settlement_batches.csv",
    "settlement_lines": "settlement_lines.csv",
    "bank_statement": "bank_statement.csv",
    "invoices": "invoices.csv",
    "ledger": "ledger.csv",
}


@pytest.mark.parametrize("dataset", sorted(DATASET_FILES))
def test_every_generated_row_normalises_without_rejection(generated, dataset):
    """The integration point. The generator and the normalisers were built
    days apart against the same spec; this is what proves they agree."""
    path = generated / DATASET_FILES[dataset]
    normalizer = get_normalizer(dataset)

    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows, f"{dataset} produced no rows to check"

    rejections = []
    accepted = []
    for i, row in enumerate(rows, start=2):   # start=2: header is line 1
        try:
            accepted.append(normalizer.normalise(row, business_timezone=IST))
        except RejectionError as exc:
            rejections.append(f"line {i}: {exc.code} on {exc.column!r} = {exc.value!r} - {exc}")

    assert not rejections, (
        f"{len(rejections)} of {len(rows)} {dataset} rows were rejected:\n  "
        + "\n  ".join(rejections[:10])
    )
    assert len(accepted) == len(rows)


def test_normalised_amounts_round_trip_against_the_source(generated):
    """Formatting to CSV and parsing back must not move a paise."""
    path = generated / "settlement_batches.csv"
    normalizer = get_normalizer("settlement_batches")
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            txn = normalizer.normalise(row, business_timezone=IST)
            assert (
                txn.gross_amount_minor - txn.fee_amount_minor - txn.tax_amount_minor
                == txn.net_amount_minor
            )


def test_settlement_lines_expose_both_join_keys(generated):
    """R1 needs the payment; grouping needs the batch. Both must be
    columns, not metadata, so the matching SQL can use an index."""
    path = generated / "settlement_lines.csv"
    normalizer = get_normalizer("settlement_lines")
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            txn = normalizer.normalise(row, business_timezone=IST)
            assert txn.parent_external_id, "settlement line must name its payment"
            assert txn.reference_id, "settlement line must name its batch"
            assert txn.reference_id.startswith("setl_")


def test_payments_and_invoices_share_the_order_id_join_key(generated):
    """R4 joins these two on reference_id, so both sides must populate it
    from the same underlying value."""
    with (generated / "payments.csv").open(newline="", encoding="utf-8") as f:
        pay_rows = [r for r in csv.DictReader(f) if r["record_type"] == "payment"][:50]
    with (generated / "invoices.csv").open(newline="", encoding="utf-8") as f:
        inv_by_order = {r["order_id"]: r for r in csv.DictReader(f)}

    pay_n = get_normalizer("payments")
    inv_n = get_normalizer("invoices")

    matched = 0
    for row in pay_rows:
        invoice_row = inv_by_order.get(row["order_id"])
        if invoice_row is None:
            continue
        payment = pay_n.normalise(row, business_timezone=IST)
        invoice = inv_n.normalise(invoice_row, business_timezone=IST)
        assert payment.reference_id == invoice.reference_id
        matched += 1

    assert matched > 0, "no payment/invoice pairs were available to check"


def test_most_clean_records_carry_no_blocking_flags(generated):
    """A non-empty `data_quality_flags` blocks auto-resolution outright,
    so a flag set on nearly every record would drive the auto-resolution
    rate to zero while every individual test still passed.

    An assumed timezone is the specific trap: bank statements are always
    date-only and many gateway exports have no offset, so flagging it
    marks the whole dataset. It belongs in `tz_assumed`, not here.
    """
    unflagged = flagged = 0
    for dataset, filename in DATASET_FILES.items():
        normalizer = get_normalizer(dataset)
        with (generated / filename).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                txn = normalizer.normalise(row, business_timezone=IST)
                assert "timezone_assumed" not in txn.data_quality_flags, (
                    "an assumed timezone is provenance, not a data-quality defect; "
                    "it must not block auto-resolution"
                )
                if txn.data_quality_flags:
                    flagged += 1
                else:
                    unflagged += 1

    total = flagged + unflagged
    assert total > 100, "not enough records to draw a conclusion"
    # The injected anomalies are a small minority by design, so the clean
    # majority must be able to reach auto-resolution.
    assert unflagged / total > 0.8, (
        f"only {unflagged}/{total} records are unflagged - a flag this common "
        "would make auto-resolution impossible"
    )


def test_timezone_assumption_is_still_recorded_just_not_as_a_flag(generated):
    """Removing the flag must not lose the information."""
    normalizer = get_normalizer("bank_statement")
    with (generated / "bank_statement.csv").open(newline="", encoding="utf-8") as f:
        txns = [normalizer.normalise(r, business_timezone=IST) for r in csv.DictReader(f)]

    assert txns
    # Bank statements are date-only, so every row assumed a timezone.
    assert all(t.tz_assumed for t in txns)


def test_the_missing_utr_anomaly_survives_normalisation(generated):
    """The injected missing_bank_credit case must arrive at the engine as
    a flagged record, not as a rejection or a silently-filled blank."""
    path = generated / "settlement_batches.csv"
    normalizer = get_normalizer("settlement_batches")
    with path.open(newline="", encoding="utf-8") as f:
        txns = [normalizer.normalise(r, business_timezone=IST) for r in csv.DictReader(f)]

    flagged = [t for t in txns if "settlement_utr_missing" in t.data_quality_flags]
    assert flagged, "the injected missing-UTR settlements did not survive normalisation"
    for t in flagged:
        assert t.reference_id is None
