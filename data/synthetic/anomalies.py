"""The anomaly injector.

Takes the clean population `generator.py` built and deliberately breaks
twelve specific, labeled things - the controlled anomalies from
docs/01-PRD.md §15 and the exception taxonomy in the project blueprint
§10. Each injector:

1. mutates the world's records to create a real, structurally-consistent
   defect (never a row that would fail ingestion outright - these are
   *matching*-time problems, not parse errors);
2. labels the affected `ground_truth` entries with `injectedAnomaly`, so
   the evaluation harness can compute per-anomaly recall rather than one
   opaque accuracy number;
3. is independent of every other injector - each targets its own batch or
   payment via `used_batch_ids` / `used_payment_ids`, so two labels never
   land on the same record and contradict each other.

Money is only ever moved with integer arithmetic on `*_minor` fields.
Nothing here calls `float()`.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .model import BankTxn, LedgerEntry, World

# Default target count per anomaly, scaled against the payment population
# so a small --count run still gets at least one of each where the data
# supports it, and a large run gets proportionally more.
_RATE = 0.015

# Nine injectors compete for the same pool of settlement batches
# (delayed_settlement, missing_settlement_line, both missing-bank-credit
# variants, both duplicate variants, wrong_fee_mapping,
# wrong_ledger_amount, reference_truncated). Batches are a daily
# aggregate, not a per-payment one, so there are far fewer of them than
# there are payments - sizing their target off the payment count (as the
# payment-level injectors correctly do) starves whichever injector runs
# last. `_BATCH_SLOTS` divides the actual batch supply across the nine
# competitors instead, so every type gets a fair, non-zero share.
_BATCH_SLOTS = 9


def _target_count(world: World, minimum: int = 1) -> int:
    n = sum(1 for p in world.payments if p.record_type == "payment")
    return max(minimum, round(n * _RATE))


def _batch_target_count(world: World, minimum: int = 1) -> int:
    return max(minimum, len(world.batches) // _BATCH_SLOTS)


def _recompute_batch_from_lines(world: World, batch_id: str) -> None:
    lines = world.lines_for_batch(batch_id)
    batch = next(b for b in world.batches if b.batch_id == batch_id)
    batch.gross_minor = sum(ln.gross_minor for ln in lines)
    batch.fee_minor = sum(ln.fee_minor for ln in lines)
    batch.tax_minor = sum(ln.tax_minor for ln in lines)
    batch.net_minor = sum(ln.net_minor for ln in lines)


def _mark_batch_ground_truth(world: World, batch_id: str, anomaly: str) -> None:
    for gt in world.ground_truth_for_batch(batch_id):
        gt["injectedAnomaly"] = anomaly


def _find_bank_txn(world: World, batch_id: str) -> BankTxn | None:
    """The bank credit that (before injection) matched this batch by amount+UTR."""
    batch = next(b for b in world.batches if b.batch_id == batch_id)
    for b in world.bank:
        if b.reference == batch.payout_utr:
            return b
    return None


# --------------------------------------------------------------------------
# 1. Delayed settlement - date_mismatch
# --------------------------------------------------------------------------

def _inject_delayed_settlement(world: World, rng: random.Random,
                                used_batch_ids: set[str]) -> int:
    """Push a batch's settlement (and its bank credit) past the T+3 window.

    Amounts stay exact. The only thing wrong is timing - this is meant to
    be matchable at lower confidence, and specifically NOT auto-resolved
    (PRD §9: date_mismatch inside tolerance but outside the window is
    flagged, never cleared silently).
    """
    candidates = [b for b in world.batches if b.batch_id not in used_batch_ids]
    n_target = _batch_target_count(world)
    injected = 0
    for batch in rng.sample(candidates, k=min(n_target, len(candidates))):
        delay = timedelta(days=rng.choice((4, 5, 6)))
        old_date = date.fromisoformat(batch.settled_at[:10])
        new_date = old_date + delay

        batch.settled_at = batch.settled_at.replace(batch.settled_at[:10], new_date.isoformat())
        bank_txn = _find_bank_txn(world, batch.batch_id)
        if bank_txn:
            bank_txn.txn_date = new_date.isoformat()
            bank_txn.bank_txn_id = f"BNK{new_date.strftime('%Y%m%d')}-{rng.randint(9000, 9999)}"

        used_batch_ids.add(batch.batch_id)
        _mark_batch_ground_truth(world, batch.batch_id, "delayed_settlement")
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 2. Missing settlement line - unmatched_payment
# --------------------------------------------------------------------------

def _inject_missing_settlement_line(world: World, rng: random.Random,
                                     used_batch_ids: set[str]) -> int:
    """Drop one line from an otherwise-valid, multi-line batch.

    The batch is recomputed from its remaining lines, so R3 (batch total =
    Σ lines) still holds for what is left - the defect is that one payment
    silently has no settlement link at all, as if the export simply
    dropped a row.
    """
    eligible = [b for b in world.batches
                if b.batch_id not in used_batch_ids and len(world.lines_for_batch(b.batch_id)) >= 3]
    n_target = _batch_target_count(world)
    injected = 0
    for batch in rng.sample(eligible, k=min(n_target, len(eligible))):
        lines = world.lines_for_batch(batch.batch_id)
        dropped = rng.choice(lines)
        world.lines.remove(dropped)
        _recompute_batch_from_lines(world, batch.batch_id)

        # The bank credit and ledger must still reflect what actually
        # arrived - i.e. the batch minus the dropped line's net - so the
        # rest of the batch stays internally consistent.
        bank_txn = _find_bank_txn(world, batch.batch_id)
        if bank_txn:
            bank_txn.amount_minor -= dropped.net_minor
        for entry in world.ledger_for_batch(batch.batch_id):
            if entry.account == "1010-Bank":
                entry.debit_minor -= dropped.net_minor
            elif entry.account == "5210-PaymentGatewayFees":
                entry.debit_minor -= dropped.fee_minor
            elif entry.account == "1450-GSTInputCredit":
                entry.debit_minor -= dropped.tax_minor
            elif entry.account == "4000-Revenue":
                entry.credit_minor -= dropped.gross_minor

        for gt in world.ground_truth:
            if dropped.payment_id in gt["externalIds"]:
                gt["injectedAnomaly"] = "missing_settlement_line"

        used_batch_ids.add(batch.batch_id)
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 3 & 4. Missing bank credit - single candidate vs. ambiguous
# --------------------------------------------------------------------------

def _inject_missing_bank_credit_single(world: World, rng: random.Random,
                                        used_batch_ids: set[str]) -> int:
    """Blank the UTR, both on the batch and in the bank narration.

    Amount and date still corroborate exactly one bank credit, so a
    scored rule *could* match this with reasonable confidence - but
    `missing_bank_credit` is on the policy's `never_auto_resolve` list
    (PRD §5.3), so even a clean single-candidate case must still route to
    review. This is what demonstrates that the block list is a real
    override, not just what low confidence would have produced anyway.
    """
    eligible = [b for b in world.batches if b.batch_id not in used_batch_ids and b.payout_utr]
    n_target = _batch_target_count(world)
    injected = 0
    for batch in rng.sample(eligible, k=min(n_target, len(eligible))):
        bank_txn = _find_bank_txn(world, batch.batch_id)
        if bank_txn is None:
            continue
        bank_txn.reference = ""
        bank_txn.description = "NEFT CR-RAZORPAY SOFTWARE PVT LTD"
        batch.payout_utr = ""

        used_batch_ids.add(batch.batch_id)
        _mark_batch_ground_truth(world, batch.batch_id, "missing_bank_credit_single")
        injected += 1
    return injected


def _inject_missing_bank_credit_ambiguous(world: World, rng: random.Random,
                                           used_batch_ids: set[str],
                                           balance_tracker: list[int]) -> int:
    """The flagship abstention case.

    Same UTR-blanking as the single-candidate version, plus a second,
    unrelated bank credit for the exact same net amount landing inside
    the same T+0..T+3 window. Two candidates now satisfy amount and date
    equally well; the required 0.05 score margin cannot be met, and the
    engine must show both and resolve neither (PRD §6.3's flagship case,
    already mirrored in the frontend's fixture data).
    """
    eligible = [b for b in world.batches if b.batch_id not in used_batch_ids and b.payout_utr]
    n_target = _batch_target_count(world, minimum=1)
    injected = 0
    for batch in rng.sample(eligible, k=min(n_target, len(eligible))):
        bank_txn = _find_bank_txn(world, batch.batch_id)
        if bank_txn is None:
            continue

        bank_txn.reference = ""
        bank_txn.description = "NEFT CR-RAZORPAY SOFTWARE PVT LTD"
        batch.payout_utr = ""

        settle_date = date.fromisoformat(bank_txn.txn_date)
        decoy_date = settle_date + timedelta(days=rng.choice((0, 1)))
        if decoy_date.weekday() >= 5:
            decoy_date = settle_date

        balance_tracker[0] += batch.net_minor
        decoy = BankTxn(
            bank_txn_id=f"BNK{decoy_date.strftime('%Y%m%d')}-{rng.randint(9000, 9999)}",
            txn_date=decoy_date.isoformat(),
            amount_minor=batch.net_minor,
            direction="credit",
            reference=f"UTR{rng.randint(700000, 799999)}",
            description="NEFT CR-RAZORPAY SOFTWARE-" + f"UTR{rng.randint(700000, 799999)}",
            balance_minor=balance_tracker[0],
        )
        world.bank.append(decoy)

        used_batch_ids.add(batch.batch_id)
        _mark_batch_ground_truth(world, batch.batch_id, "missing_bank_credit_ambiguous")
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 5 & 6. Duplicates
# --------------------------------------------------------------------------

def _inject_duplicate_bank_row(world: World, rng: random.Random,
                                used_batch_ids: set[str],
                                balance_tracker: list[int]) -> int:
    """A bank credit that has genuinely been presented twice.

    Different `bank_txn_id` (it is a distinct row in the export, not a
    key collision an ingestion-level uniqueness check would already
    catch), same reference, amount, and date - the shape of a bank export
    that accidentally repeats a line item.
    """
    # Filtered to unused batches *before* sampling, like every other
    # injector here. Filtering inside the loop instead (checking
    # eligibility after the sample is drawn) would silently under-deliver
    # whenever the sample happened to land on an already-claimed batch -
    # the count is correct either way, but pre-filtering is what makes it
    # reliably hit its target rather than depending on luck.
    eligible = [
        b for b in world.bank
        if b.direction == "credit"
        and any(bt.payout_utr == b.reference and bt.batch_id not in used_batch_ids
                for bt in world.batches)
    ]
    n_target = _batch_target_count(world)
    injected = 0
    for original in rng.sample(eligible, k=min(n_target, len(eligible))):
        batch = next(bt for bt in world.batches if bt.payout_utr == original.reference)
        if batch.batch_id in used_batch_ids:
            continue  # claimed by an earlier draw in this same loop

        balance_tracker[0] += original.amount_minor
        clone = BankTxn(
            bank_txn_id=f"BNK{original.txn_date.replace('-', '')}-{rng.randint(9000, 9999)}",
            txn_date=original.txn_date, amount_minor=original.amount_minor,
            direction="credit", reference=original.reference,
            description=original.description, balance_minor=balance_tracker[0],
        )
        world.bank.append(clone)

        used_batch_ids.add(batch.batch_id)
        _mark_batch_ground_truth(world, batch.batch_id, "duplicate_bank_row")
        injected += 1
    return injected


def _inject_duplicate_ledger_entry(world: World, rng: random.Random,
                                    used_batch_ids: set[str]) -> int:
    """An accidental second posting of the same revenue line.

    Same reference and amount, a new `journal_id` - the shape of a
    journal being posted twice by mistake, which silently inflates
    recognised revenue if it is not caught.
    """
    # Pre-filtered by used_batch_ids, same reasoning as duplicate_bank_row.
    revenue_lines = [
        e for e in world.ledger
        if e.account == "4000-Revenue" and e.reference not in used_batch_ids
    ]
    n_target = _batch_target_count(world)
    injected = 0
    seq = 9000
    for original in rng.sample(revenue_lines, k=min(n_target, len(revenue_lines))):
        batch_id = original.reference
        if batch_id in used_batch_ids:
            continue  # claimed by an earlier draw in this same loop
        ym = original.journal_id.split("-")[1] + "-" + original.journal_id.split("-")[2]
        clone = LedgerEntry(
            journal_id=f"JNL-{ym}-{seq}", account=original.account,
            debit_minor=original.debit_minor, credit_minor=original.credit_minor,
            reference=original.reference, posted_at=original.posted_at,
        )
        world.ledger.append(clone)
        seq += 1

        used_batch_ids.add(batch_id)
        _mark_batch_ground_truth(world, batch_id, "duplicate_ledger_entry")
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 7. Wrong fee mapping - fee_tax_discrepancy
# --------------------------------------------------------------------------

def _inject_wrong_fee_mapping(world: World, rng: random.Random,
                               used_batch_ids: set[str]) -> int:
    """Recompute an entire batch's fee at the wrong basis-point rate.

    The batch stays internally consistent - `gross - fee - tax = net`
    still holds for every line, and the lines still sum to the batch - so
    R3's integrity check does not fire. What is wrong is that the applied
    rate does not match `manifest.json`'s fee schedule for the methods
    actually used, which is what a policy-driven expectation check (not
    an internal-consistency check) is meant to catch.
    """
    candidates = [b for b in world.batches if b.batch_id not in used_batch_ids]
    n_target = _batch_target_count(world)
    injected = 0
    for batch in rng.sample(candidates, k=min(n_target, len(candidates))):
        lines = world.lines_for_batch(batch.batch_id)
        if not lines:
            continue
        wrong_bps = rng.choice((350, 400, 90))  # neither a real per-method rate

        for line in lines:
            line.fee_minor = line.gross_minor * wrong_bps // 10_000
            line.tax_minor = line.fee_minor * 1800 // 10_000
            line.net_minor = line.gross_minor - line.fee_minor - line.tax_minor

        old_net = batch.net_minor
        _recompute_batch_from_lines(world, batch.batch_id)
        delta = batch.net_minor - old_net

        bank_txn = _find_bank_txn(world, batch.batch_id)
        if bank_txn:
            bank_txn.amount_minor += delta
        for entry in world.ledger_for_batch(batch.batch_id):
            if entry.account == "1010-Bank":
                entry.debit_minor = batch.net_minor
            elif entry.account == "5210-PaymentGatewayFees":
                entry.debit_minor = batch.fee_minor
            elif entry.account == "1450-GSTInputCredit":
                entry.debit_minor = batch.tax_minor
            # Revenue credit is unchanged: gross does not move.

        used_batch_ids.add(batch.batch_id)
        _mark_batch_ground_truth(world, batch.batch_id, "wrong_fee_mapping")
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 8. Wrong ledger amount - amount_mismatch
# --------------------------------------------------------------------------

def _inject_wrong_ledger_amount(world: World, rng: random.Random,
                                 used_batch_ids: set[str]) -> int:
    """Post revenue net of GST on the fee, instead of gross.

    `Σdebits == Σcredits` now fails by exactly the batch's tax amount -
    the bank and settlement records are untouched and correct, so this
    isolates the defect to the ledger, matching the frontend's own case
    fixture ("ledger revenue posting excludes the GST component").
    """
    candidates = [b for b in world.batches if b.batch_id not in used_batch_ids]
    n_target = _batch_target_count(world)
    injected = 0
    for batch in rng.sample(candidates, k=min(n_target, len(candidates))):
        revenue = next((e for e in world.ledger_for_batch(batch.batch_id)
                         if e.account == "4000-Revenue"), None)
        if revenue is None or batch.tax_minor == 0:
            continue
        revenue.credit_minor -= batch.tax_minor

        used_batch_ids.add(batch.batch_id)
        _mark_batch_ground_truth(world, batch.batch_id, "wrong_ledger_amount")
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 9. Refund with no original payment in the dataset - refund_unlinked
# --------------------------------------------------------------------------

def _inject_refund_unlinked(world: World, rng: random.Random,
                             used_payment_ids: set[str]) -> int:
    """Remove a refund's parent payment from the export entirely.

    Simulates a payment captured before the snapshot's date range: the
    refund is real and present, but the record it should link to simply
    is not in this dataset. The engine must name the missing source
    rather than netting the refund off a plausible-looking stranger.
    """
    refunds = [p for p in world.payments
               if p.record_type == "refund" and p.parent_payment_id not in used_payment_ids]
    n_target = _target_count(world, minimum=1)
    injected = 0
    for refund in rng.sample(refunds, k=min(n_target, len(refunds))):
        parent = next((p for p in world.payments if p.payment_id == refund.parent_payment_id), None)
        if parent is None:
            continue
        world.payments.remove(parent)
        used_payment_ids.add(parent.payment_id)

        world.ground_truth.append({
            "truthId": f"truth_{refund.payment_id}",
            "relationType": "refund_unlinked",
            "externalIds": [refund.payment_id],
            "expectedGroup": None,
            "injectedAnomaly": "refund_unlinked",
        })
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 10. Status conflict
# --------------------------------------------------------------------------

def _inject_status_conflict(world: World, rng: random.Random,
                             used_payment_ids: set[str]) -> int:
    """The gateway says captured; the invoice system still says unpaid.

    Models a webhook or sync failure - the source systems genuinely
    disagree, which is a real category the engine must surface rather
    than silently trust one side.
    """
    paid_captured = [
        p for p in world.payments
        if p.status == "captured" and p.payment_id not in used_payment_ids
    ]
    n_target = _target_count(world)
    injected = 0
    for payment in rng.sample(paid_captured, k=min(n_target, len(paid_captured))):
        invoice = next((i for i in world.invoices if i.order_id == payment.order_id), None)
        if invoice is None or invoice.status != "paid":
            continue
        invoice.status = "unpaid"
        invoice.amount_paid_minor = 0

        for gt in world.ground_truth:
            if payment.payment_id in gt["externalIds"]:
                gt["injectedAnomaly"] = "status_conflict"
        used_payment_ids.add(payment.payment_id)
        injected += 1
    return injected


# --------------------------------------------------------------------------
# 11. Truncated / typo'd bank reference
# --------------------------------------------------------------------------

def _inject_reference_truncated(world: World, rng: random.Random,
                                 used_batch_ids: set[str]) -> int:
    """Garble the UTR in the narration without breaking the match.

    A real prefix is kept (enough for prefix-plus-corroboration matching,
    PRD §6.3) but the full reference no longer round-trips exactly - this
    is meant to still resolve, at lower confidence via a softer rule
    rather than the exact-reference one, so it exercises recall on a
    harder-but-fair case rather than another abstention.
    """
    eligible = [b for b in world.batches if b.batch_id not in used_batch_ids and b.payout_utr]
    n_target = _batch_target_count(world)
    injected = 0
    for batch in rng.sample(eligible, k=min(n_target, len(eligible))):
        bank_txn = _find_bank_txn(world, batch.batch_id)
        if bank_txn is None:
            continue
        prefix = bank_txn.reference[:7]  # "UTR7739" - drops the last 2-3 digits
        bank_txn.reference = prefix
        bank_txn.description = f"NEFT CR-RAZORPAY SOFTWARE-{prefix}"

        used_batch_ids.add(batch.batch_id)
        _mark_batch_ground_truth(world, batch.batch_id, "reference_truncated")
        injected += 1
    return injected


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def inject_anomalies(world: World, rng: random.Random) -> None:
    """Run every injector once, in a fixed order, and record what fired.

    Order matters only in that earlier injectors claim batches first;
    later ones simply see a smaller eligible pool. Each injector is
    individually tolerant of a too-small population - it injects as many
    as it can find eligible targets for and reports the true count, it
    never raises.
    """
    used_batch_ids: set[str] = set()
    used_payment_ids: set[str] = set()
    opening_balance = world.bank[-1].balance_minor if world.bank else 100_00000
    balance_tracker = [opening_balance]

    counts = {
        "delayed_settlement": _inject_delayed_settlement(world, rng, used_batch_ids),
        "missing_settlement_line": _inject_missing_settlement_line(world, rng, used_batch_ids),
        "missing_bank_credit_single": _inject_missing_bank_credit_single(
            world, rng, used_batch_ids),
        "missing_bank_credit_ambiguous": _inject_missing_bank_credit_ambiguous(
            world, rng, used_batch_ids, balance_tracker),
        "duplicate_bank_row": _inject_duplicate_bank_row(
            world, rng, used_batch_ids, balance_tracker),
        "duplicate_ledger_entry": _inject_duplicate_ledger_entry(world, rng, used_batch_ids),
        "wrong_fee_mapping": _inject_wrong_fee_mapping(world, rng, used_batch_ids),
        "wrong_ledger_amount": _inject_wrong_ledger_amount(world, rng, used_batch_ids),
        "refund_unlinked": _inject_refund_unlinked(world, rng, used_payment_ids),
        "status_conflict": _inject_status_conflict(world, rng, used_payment_ids),
        "reference_truncated": _inject_reference_truncated(world, rng, used_batch_ids),
    }
    world.anomaly_counts = counts
