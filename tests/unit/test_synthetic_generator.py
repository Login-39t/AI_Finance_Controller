"""Tests for the synthetic data generator and anomaly injector.

These are not a nicety - the whole evaluation story depends on the
generator producing data whose ground truth is actually true. A bug here
means every downstream precision/recall number is measuring the wrong
thing without saying so.

Run at a small, fast scale (`count=120`) so the whole file finishes in
well under a second; the CLI defaults to 1200 for a demo-sized dataset.
"""

from __future__ import annotations

import random

import pytest

from data.synthetic.anomalies import inject_anomalies
from data.synthetic.generator import assign_partition, generate_world

SEED = 7
COUNT = 120


@pytest.fixture(scope="module")
def world():
    w = generate_world(COUNT, SEED, lookback_days=30)
    inject_anomalies(w, random.Random(SEED ^ 0x5EED))
    return w


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

def test_same_seed_produces_identical_populations():
    a = generate_world(COUNT, SEED, lookback_days=30)
    b = generate_world(COUNT, SEED, lookback_days=30)
    assert [p.payment_id for p in a.payments] == [p.payment_id for p in b.payments]
    assert [p.amount_minor for p in a.payments] == [p.amount_minor for p in b.payments]
    assert [b_.net_minor for b_ in a.batches] == [b_.net_minor for b_ in b.batches]


def test_different_seed_produces_different_populations():
    a = generate_world(COUNT, SEED, lookback_days=30)
    b = generate_world(COUNT, SEED + 1, lookback_days=30)
    assert [p.payment_id for p in a.payments] != [p.payment_id for p in b.payments]


def test_partition_is_stable_regardless_of_call_order():
    """The eval harness must never be able to shuffle a record between
    tuning and holdout by regenerating in a different order."""
    ids = [f"truth_pay_{i}" for i in range(50)]
    first = [assign_partition(SEED, tid) for tid in ids]
    second = [assign_partition(SEED, tid) for tid in reversed(ids)]
    assert first == list(reversed(second))


def test_holdout_fraction_is_close_to_requested():
    ids = [f"truth_pay_{i}" for i in range(2000)]
    holdout = sum(1 for tid in ids if assign_partition(SEED, tid) == "holdout")
    # Not exact - it's a hash bucket, not a shuffle-and-slice - but should
    # land close to the requested 20%.
    assert 0.15 <= holdout / len(ids) <= 0.25


# --------------------------------------------------------------------------
# Money identities - the whole point of generating in integer minor units
# --------------------------------------------------------------------------

def test_every_settlement_line_satisfies_the_amount_identity(world):
    for line in world.lines:
        assert line.gross_minor - line.fee_minor - line.tax_minor == line.net_minor


def test_every_batch_satisfies_the_amount_identity(world):
    for batch in world.batches:
        assert batch.gross_minor - batch.fee_minor - batch.tax_minor == batch.net_minor


def test_batch_totals_equal_sum_of_lines_except_where_a_line_was_deliberately_dropped(world):
    """This is R3. It must hold everywhere except the one labeled anomaly
    whose entire point is to break it."""
    broken = {
        eid
        for g in world.ground_truth
        if g.get("injectedAnomaly") == "missing_settlement_line"
        for eid in g["externalIds"]
        if eid.startswith("setl_")
    }
    checked = 0
    for batch in world.batches:
        if batch.batch_id in broken:
            continue
        lines = world.lines_for_batch(batch.batch_id)
        assert sum(ln.gross_minor for ln in lines) == batch.gross_minor
        assert sum(ln.fee_minor for ln in lines) == batch.fee_minor
        assert sum(ln.tax_minor for ln in lines) == batch.tax_minor
        assert sum(ln.net_minor for ln in lines) == batch.net_minor
        checked += 1
    assert checked > 0, "no clean batches were available to check - test is vacuous"


def test_ledger_debits_equal_credits_except_where_deliberately_broken(world):
    """Σdebits == Σcredits per journal reference, except the two anomalies
    whose entire point is to break that identity."""
    broken = {
        eid
        for g in world.ground_truth
        if g.get("injectedAnomaly") in ("wrong_ledger_amount", "missing_settlement_line",
                                          "duplicate_ledger_entry")
        for eid in g["externalIds"]
        if eid.startswith("setl_")
    }
    by_ref: dict[str, list] = {}
    for entry in world.ledger:
        by_ref.setdefault(entry.reference, []).append(entry)

    checked = 0
    for ref, entries in by_ref.items():
        if ref in broken:
            continue
        debits = sum(e.debit_minor for e in entries)
        credits = sum(e.credit_minor for e in entries)
        assert debits == credits, f"{ref}: debits={debits} credits={credits}"
        checked += 1
    assert checked > 0, "no clean journals were available to check - test is vacuous"


def test_no_float_anywhere_in_the_record_fields(world):
    """A structural guard: every *_minor field is an int, always."""
    for p in world.payments:
        assert isinstance(p.amount_minor, int)
    for b in world.batches:
        assert isinstance(b.net_minor, int)
    for line in world.lines:
        assert isinstance(line.net_minor, int)
    for tx in world.bank:
        assert isinstance(tx.amount_minor, int)
    for entry in world.ledger:
        assert isinstance(entry.debit_minor, int)
        assert isinstance(entry.credit_minor, int)


# --------------------------------------------------------------------------
# Identity hygiene
# --------------------------------------------------------------------------

def test_no_accidental_duplicate_ids(world):
    """Real ID collisions (as opposed to deliberately duplicated rows,
    which always get a *new* id) must never happen."""
    def assert_unique(ids, label):
        seen = set()
        dupes = [i for i in ids if i in seen or seen.add(i)]
        assert not dupes, f"{label} has accidental duplicate ids: {dupes}"

    assert_unique([p.payment_id for p in world.payments], "payment_id")
    assert_unique([tx.bank_txn_id for tx in world.bank], "bank_txn_id")
    assert_unique([e.journal_id for e in world.ledger], "journal_id")
    assert_unique([ln.settlement_id for ln in world.lines], "settlement_id")
    assert_unique([i.invoice_id for i in world.invoices], "invoice_id")


# --------------------------------------------------------------------------
# Anomaly injector coverage - the bug this suite exists to catch
# --------------------------------------------------------------------------

EXPECTED_ANOMALY_TYPES = {
    "delayed_settlement",
    "missing_settlement_line",
    "missing_bank_credit_single",
    "missing_bank_credit_ambiguous",
    "duplicate_bank_row",
    "duplicate_ledger_entry",
    "wrong_fee_mapping",
    "wrong_ledger_amount",
    "refund_unlinked",
    "status_conflict",
    "reference_truncated",
}


def test_every_anomaly_type_fires_at_least_once(world):
    """The regression this suite is built to prevent: a sizing bug in the
    injector silently zeroing out several anomaly types while the run
    still 'succeeds'. Every type must produce at least one instance."""
    zero = {k for k, v in world.anomaly_counts.items() if v == 0}
    assert not zero, f"these anomaly types produced zero instances: {zero}"
    assert set(world.anomaly_counts) == EXPECTED_ANOMALY_TYPES


def test_missing_bank_credit_ambiguous_actually_has_two_competing_candidates(world):
    """The flagship abstention case. If this degrades to one candidate,
    it silently stops being ambiguous and the demo's central claim - that
    the engine abstains rather than guessing - has nothing to point at."""
    batch_ids = {
        eid
        for g in world.ground_truth
        if g.get("injectedAnomaly") == "missing_bank_credit_ambiguous"
        for eid in g["externalIds"]
        if eid.startswith("setl_")
    }
    assert batch_ids, "no missing_bank_credit_ambiguous batch was produced at this scale"

    for batch_id in batch_ids:
        batch = next(b for b in world.batches if b.batch_id == batch_id)
        assert batch.payout_utr == "", "the batch's own UTR must be blanked"
        candidates = [
            tx for tx in world.bank
            if tx.amount_minor == batch.net_minor and tx.direction == "credit"
        ]
        assert len(candidates) >= 2, (
            f"{batch_id} has only {len(candidates)} amount-matching bank credit(s), "
            "not enough to be genuinely ambiguous"
        )
        # Ambiguity requires that no candidate can be singled out by an
        # exact-reference rule (R2). The batch's own UTR is already gone
        # (asserted above), so the only way a candidate could still
        # resolve cleanly is if it happened to carry that same UTR - which
        # can't happen once it's blank - or if two candidates shared a
        # reference with each other, which would make them indistinguishable
        # for the wrong reason (a literal duplicate) rather than a genuine
        # multi-candidate match. Neither may occur here.
        refs = [tx.reference for tx in candidates if tx.reference]
        assert len(refs) == len(set(refs)), (
            "candidates must not share a reference with each other - that "
            "would be a duplicate, not the amount/date ambiguity under test"
        )


def test_refund_unlinked_parent_is_genuinely_absent(world):
    unlinked = [g for g in world.ground_truth if g.get("injectedAnomaly") == "refund_unlinked"]
    assert unlinked, "no refund_unlinked instance was produced at this scale"
    payment_ids = {p.payment_id for p in world.payments}
    for g in unlinked:
        refund_id = g["externalIds"][0]
        refund = next(p for p in world.payments if p.payment_id == refund_id)
        assert refund.parent_payment_id not in payment_ids, (
            "the refund's parent payment must not be present in the dataset"
        )


def test_status_conflict_invoice_disagrees_with_a_captured_payment(world):
    conflicts = [
        g for g in world.ground_truth if g.get("injectedAnomaly") == "status_conflict"
    ]
    assert conflicts, "no status_conflict instance was produced at this scale"
    for g in conflicts:
        payment_id = next(e for e in g["externalIds"] if e.startswith("pay_"))
        payment = next(p for p in world.payments if p.payment_id == payment_id)
        invoice = next(i for i in world.invoices if i.order_id == payment.order_id)
        assert payment.status == "captured"
        assert invoice.status == "unpaid"
        assert invoice.amount_paid_minor == 0


def test_wrong_ledger_amount_breaks_by_exactly_the_tax_component(world):
    broken = [g for g in world.ground_truth if g.get("injectedAnomaly") == "wrong_ledger_amount"]
    assert broken, "no wrong_ledger_amount instance was produced at this scale"
    for g in broken:
        batch_id = next(e for e in g["externalIds"] if e.startswith("setl_"))
        batch = next(b for b in world.batches if b.batch_id == batch_id)
        entries = world.ledger_for_batch(batch_id)
        debits = sum(e.debit_minor for e in entries)
        credits = sum(e.credit_minor for e in entries)
        assert debits - credits == batch.tax_minor


def test_wrong_fee_mapping_stays_internally_consistent(world):
    """The batch's own arithmetic must still hold - only the *rate* is
    wrong relative to the fee schedule, never the batch's internal sum."""
    broken = [g for g in world.ground_truth if g.get("injectedAnomaly") == "wrong_fee_mapping"]
    assert broken, "no wrong_fee_mapping instance was produced at this scale"
    for g in broken:
        batch_id = next(e for e in g["externalIds"] if e.startswith("setl_"))
        batch = next(b for b in world.batches if b.batch_id == batch_id)
        lines = world.lines_for_batch(batch_id)
        assert sum(ln.net_minor for ln in lines) == batch.net_minor
        assert batch.gross_minor - batch.fee_minor - batch.tax_minor == batch.net_minor


def test_duplicate_rows_share_business_content_but_not_identity(world):
    dup_bank = [g for g in world.ground_truth if g.get("injectedAnomaly") == "duplicate_bank_row"]
    assert dup_bank, "no duplicate_bank_row instance was produced at this scale"
    for g in dup_bank:
        batch_id = next(e for e in g["externalIds"] if e.startswith("setl_"))
        matches = [tx for tx in world.bank
                   if tx.amount_minor == next(b for b in world.batches
                                               if b.batch_id == batch_id).net_minor]
        assert len(matches) >= 2
        ids = {tx.bank_txn_id for tx in matches}
        assert len(ids) == len(matches), "duplicated rows must not share an id"
