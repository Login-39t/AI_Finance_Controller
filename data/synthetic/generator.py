"""Synthetic dataset generator.

Produces five source files that look like real exports - payments,
settlement batches, settlement lines, bank statement, invoices, ledger -
plus a ground-truth file recording the ID chain that *should* link across
them and, where deliberate, which labeled defect was injected.

Two design choices carry the rest of this file:

1. **All money is generated as integer paise and converted to a decimal
   string only at write time** (see `model.py`'s `row()` methods), via the
   same `format_minor` the frontend and, eventually, the ingestion layer
   use. Every arithmetic identity the engine will check - `net = gross -
   fee - tax`, batch totals equal to the sum of their lines, `Σdebits ==
   Σcredits` - is exact by construction, the same way the real system
   requires it to be.

2. **The dataset is deterministic given a seed.** A fixed end date and a
   dedicated `random.Random` instance (never the global `random` module)
   mean the same `--seed` always produces the same files, which is what
   lets a rule change be judged against a stable held-out partition
   instead of a coin flip.

Usage:
    python -m data.synthetic.generator --count 1200 --seed 42
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Make packages/domain importable when this file is run directly, the same
# pattern used in backend/alembic/env.py, so `python data/synthetic/generator.py`
# and `python -m data.synthetic.generator` both work without PYTHONPATH set.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "domain"))

from .anomalies import inject_anomalies  # noqa: E402
from .model import (  # noqa: E402
    CURRENCY,
    BankTxn,
    Invoice,
    LedgerEntry,
    Payment,
    SettlementBatch,
    SettlementLine,
    World,
)

BUSINESS_TZ = ZoneInfo("Asia/Kolkata")

# Fixed anchor rather than date.today(): reproducibility means the same
# seed produces byte-identical files regardless of when it is run. This
# also lines up with the run_id already used in the frontend fixtures
# (run_2026_03_04_0912), so a demo walking from generator to UI is coherent.
END_DATE = date(2026, 3, 4)
DEFAULT_LOOKBACK_DAYS = 30

# Fee schedule: 2% + 18% GST on the fee is the PRD's stated working
# assumption (docs/01-PRD.md Q2). Per-method rates add the variety that
# makes "wrong fee mapping" a meaningful, detectable anomaly rather than
# a single hardcoded number nothing could ever disagree with.
DEFAULT_FEE_BPS = 200
GST_BPS_ON_FEE = 1800
METHOD_FEE_BPS = {
    "upi": 150,
    "card": 250,
    "netbanking": 200,
    "wallet": 180,
}
METHODS = tuple(METHOD_FEE_BPS)

_ID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I - unambiguous on a screen


def _rand_id(rng: random.Random, n: int = 12) -> str:
    return "".join(rng.choice(_ID_ALPHABET) for _ in range(n))


def _is_business_day(d: date) -> bool:
    return d.weekday() < 5  # PRD Q1 working assumption: weekends only, no holiday calendar


def _add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    cur = d
    while remaining:
        cur += timedelta(days=step)
        if _is_business_day(cur):
            remaining -= 1
    return cur


def _business_days_between(start: date, end: date) -> list[date]:
    days = []
    cur = start
    while cur <= end:
        if _is_business_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _amount_bucket(rng: random.Random) -> int:
    """A payment amount in paise, skewed toward small tickets.

    The skew matters: it means natural amount collisions on the same day
    happen on their own, in addition to the ones deliberately injected -
    which is exactly the texture a real payments dataset has.
    """
    r = rng.random()
    if r < 0.70:
        rupees = rng.randint(199, 2999)
    elif r < 0.95:
        rupees = rng.randint(3000, 19999)
    else:
        rupees = rng.randint(20000, 49999)
    return rupees * 100


def _instant(d: date, hour: int, minute: int, second: int, *, naive: bool = False) -> str:
    """ISO-8601. `naive=True` drops the offset to exercise tz_assumed inference."""
    dt = datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=BUSINESS_TZ)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if naive else dt.isoformat()


# --------------------------------------------------------------------------
# Population
# --------------------------------------------------------------------------

def generate_world(count: int, seed: int, end_date: date = END_DATE,
                    lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> World:
    rng = random.Random(seed)
    world = World(seed=seed, end_date=end_date)

    start_date = end_date - timedelta(days=lookback_days)
    activity_days = _business_days_between(start_date, end_date)
    if not activity_days:
        raise ValueError("lookback_days produced no business days")

    running_balance = rng.randint(50_00000, 200_00000)  # an opening bank balance, in paise
    journal_seq = 1000
    invoice_seq = 100000
    bank_seq_by_date: dict[date, int] = {}

    lines_by_batch: dict[str, list[SettlementLine]] = {}

    for i in range(count):
        capture_date = rng.choice(activity_days)

        # A handful of payments are deliberately captured just before
        # midnight IST, to exercise business-date logic (PRD 6.2): the
        # settlement clock must run off the IST business date, not the
        # instant, or these look like they settled "too fast".
        late_night = i < 3
        if late_night:
            h, m, s = 23, rng.randint(50, 59), rng.randint(0, 59)
        else:
            h, m, s = rng.randint(7, 22), rng.randint(0, 59), rng.randint(0, 59)

        # ~5% of timestamps arrive with no offset, simulating a source
        # system that exports local time without a timezone marker.
        naive = rng.random() < 0.05
        created_at = _instant(capture_date, h, m, s, naive=naive)

        method = rng.choices(METHODS, weights=[45, 30, 15, 10])[0]
        gross = _amount_bucket(rng)
        payment_id = f"pay_{_rand_id(rng)}"
        order_id = f"order_{_rand_id(rng, 10)}"

        # Refund outcome, decided up front so status is consistent everywhere.
        refund_roll = rng.random()
        if refund_roll < 0.05:
            outcome = "failed"
        elif refund_roll < 0.09:
            outcome = "refunded"          # full refund
        elif refund_roll < 0.13:
            outcome = "partially_refunded"
        else:
            outcome = "captured"

        world.payments.append(Payment(
            payment_id=payment_id, order_id=order_id, amount_minor=gross,
            currency=CURRENCY, status=outcome, created_at=created_at, method=method,
        ))

        if outcome == "failed":
            # Nothing settles, no invoice is paid. Still gets an invoice
            # (an order can fail payment and simply remain unpaid).
            world.invoices.append(_make_invoice(order_id, gross, 0, "unpaid",
                                                  created_at, invoice_seq))
            invoice_seq += 1
            continue

        if outcome in ("refunded", "partially_refunded"):
            refund_amount = gross if outcome == "refunded" else rng.randint(1, gross - 1)
            refund_id = f"rfnd_{_rand_id(rng)}"
            refund_at = _instant(
                min(capture_date + timedelta(days=rng.randint(1, 5)), end_date),
                rng.randint(9, 18), rng.randint(0, 59), rng.randint(0, 59),
            )
            world.payments.append(Payment(
                payment_id=refund_id, order_id=order_id, amount_minor=refund_amount,
                currency=CURRENCY, status=outcome, created_at=refund_at, method=method,
                record_type="refund", parent_payment_id=payment_id,
            ))
            # A refunded payment is excluded from settlement in this
            # generator's model - refund netting inside a batch is a
            # deliberate out-of-scope MVP simplification (PRD §7.2, Q3).
            paid = 0 if outcome == "refunded" else gross - refund_amount
            world.invoices.append(_make_invoice(
                order_id, gross, paid,
                "unpaid" if outcome == "refunded" else "partially_paid",
                created_at, invoice_seq,
            ))
            invoice_seq += 1
            continue

        # -- captured: settles T+1..T+3 business days, forms a line -------
        settle_date = _add_business_days(capture_date, rng.choice((1, 1, 1, 2, 3)))
        if settle_date > end_date:
            # Too recent to have settled yet within the export window -
            # this is what naturally produces `unmatched_payment` cases
            # without any anomaly injection at all.
            world.invoices.append(_make_invoice(order_id, gross, gross, "paid",
                                                  created_at, invoice_seq))
            invoice_seq += 1
            continue

        fee_bps = METHOD_FEE_BPS[method]
        fee = gross * fee_bps // 10_000
        tax = fee * GST_BPS_ON_FEE // 10_000
        net = gross - fee - tax

        batch_id = f"setl_{settle_date.isoformat().replace('-', '')}"
        line = SettlementLine(
            settlement_id=f"stln_{_rand_id(rng)}", batch_id=batch_id,
            payment_id=payment_id, gross_minor=gross, fee_minor=fee,
            tax_minor=tax, net_minor=net,
        )
        lines_by_batch.setdefault(batch_id, []).append(line)
        world.lines.append(line)

        world.invoices.append(_make_invoice(order_id, gross, gross, "paid",
                                             created_at, invoice_seq))
        invoice_seq += 1

        world.ground_truth.append({
            "truthId": f"truth_{payment_id}",
            "relationType": "payment_settlement_bank_ledger",
            "externalIds": [payment_id, line.settlement_id, batch_id],
            "expectedGroup": "many_to_one",
            "injectedAnomaly": None,
        })

    # -- roll settlement lines up into batches, then a bank credit + ledger
    for batch_id, batch_lines in sorted(lines_by_batch.items()):
        raw = batch_id.removeprefix("setl_")
        settle_date = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))

        gross = sum(ln.gross_minor for ln in batch_lines)
        fee = sum(ln.fee_minor for ln in batch_lines)
        tax = sum(ln.tax_minor for ln in batch_lines)
        net = sum(ln.net_minor for ln in batch_lines)

        settled_at = _instant(settle_date, 5, 30, 0)
        utr = f"UTR{rng.randint(700000, 799999)}"

        batch = SettlementBatch(
            batch_id=batch_id, gross_minor=gross, fee_minor=fee, tax_minor=tax,
            net_minor=net, status="settled", settled_at=settled_at, payout_utr=utr,
        )
        world.batches.append(batch)

        seq = bank_seq_by_date.setdefault(settle_date, 0) + 1
        bank_seq_by_date[settle_date] = seq
        running_balance += net
        bank_txn = BankTxn(
            bank_txn_id=f"BNK{settle_date.strftime('%Y%m%d')}-{seq:04d}",
            txn_date=settle_date.isoformat(), amount_minor=net, direction="credit",
            reference=utr,
            description=f"NEFT CR-RAZORPAY SOFTWARE PVT LT-{utr}",
            balance_minor=running_balance,
        )
        world.bank.append(bank_txn)

        journal_seq = _append_ledger_for_batch(world, batch, settle_date, journal_seq)

    return world


def _make_invoice(order_id: str, due: int, paid: int, status: str,
                   near_when: str, seq: int) -> Invoice:
    issued = near_when  # invoices are issued at order time, i.e. capture time
    return Invoice(
        invoice_id=f"INV-{END_DATE.year}-{seq:06d}",
        order_id=order_id,
        customer_ref=f"cust_{seq % 4000:04d}",
        amount_due_minor=due, amount_paid_minor=paid, status=status, issued_at=issued,
    )


def _append_ledger_for_batch(world: World, batch: SettlementBatch, settle_date: date,
                              journal_seq: int) -> int:
    posted_at = settle_date.isoformat()
    ym = f"{settle_date.year}-{settle_date.month:02d}"
    rows = (
        ("1010-Bank", batch.net_minor, 0),
        ("5210-PaymentGatewayFees", batch.fee_minor, 0),
        ("1450-GSTInputCredit", batch.tax_minor, 0),
        ("4000-Revenue", 0, batch.gross_minor),
    )
    for account, debit, credit in rows:
        world.ledger.append(LedgerEntry(
            journal_id=f"JNL-{ym}-{journal_seq:04d}", account=account,
            debit_minor=debit, credit_minor=credit, reference=batch.batch_id,
            posted_at=posted_at,
        ))
        journal_seq += 1
    return journal_seq


# --------------------------------------------------------------------------
# Partitioning and output
# --------------------------------------------------------------------------

def assign_partition(seed: int, truth_id: str, holdout_fraction: float = 0.2) -> str:
    """Stable across regeneration: depends only on (seed, truth_id), never
    on generation order. Tuning against the holdout split is impossible by
    construction if the eval harness only ever reads this field.
    """
    digest = hashlib.sha256(f"{seed}:{truth_id}".encode()).hexdigest()
    bucket = int(digest, 16) % 100
    return "holdout" if bucket < int(holdout_fraction * 100) else "tuning"


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_world(world: World, out_dir: Path) -> dict:
    for gt in world.ground_truth:
        gt["partition"] = assign_partition(world.seed, gt["truthId"])

    _write_csv(out_dir / "payments.csv", [p.row() for p in world.payments],
               ["payment_id", "order_id", "amount", "currency", "status", "created_at",
                "method", "record_type", "parent_payment_id"])
    _write_csv(out_dir / "settlement_batches.csv", [b.row() for b in world.batches],
               ["batch_id", "gross", "fee", "tax", "net", "status", "settled_at", "payout_utr"])
    _write_csv(out_dir / "settlement_lines.csv", [ln.row() for ln in world.lines],
               ["settlement_id", "batch_id", "payment_id", "gross", "fee", "tax", "net"])
    _write_csv(out_dir / "bank_statement.csv", [b.row() for b in world.bank],
               ["bank_txn_id", "date", "amount", "direction", "reference", "description",
                "balance"])
    _write_csv(out_dir / "invoices.csv", [i.row() for i in world.invoices],
               ["invoice_id", "order_id", "customer_id", "amount_due", "amount_paid",
                "status", "issued_at"])
    _write_csv(out_dir / "ledger.csv", [e.row() for e in world.ledger],
               ["journal_id", "account", "debit", "credit", "reference", "posted_at", "status"])

    ground_truth_path = out_dir / "ground_truth.json"
    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    ground_truth_path.write_text(json.dumps(world.ground_truth, indent=2), encoding="utf-8")

    tuning = sum(1 for g in world.ground_truth if g["partition"] == "tuning")
    holdout = sum(1 for g in world.ground_truth if g["partition"] == "holdout")

    manifest = {
        "seed": world.seed,
        "endDate": world.end_date.isoformat(),
        "businessTimezone": str(BUSINESS_TZ),
        "currency": CURRENCY,
        "feeSchedule": {
            "defaultFeeBps": DEFAULT_FEE_BPS,
            "gstBpsOnFee": GST_BPS_ON_FEE,
            "methodFeeBps": METHOD_FEE_BPS,
        },
        "counts": {
            "payments": sum(1 for p in world.payments if p.record_type == "payment"),
            "refunds": sum(1 for p in world.payments if p.record_type == "refund"),
            "settlementBatches": len(world.batches),
            "settlementLines": len(world.lines),
            "bankTransactions": len(world.bank),
            "invoices": len(world.invoices),
            "ledgerEntries": len(world.ledger),
            "groundTruthLinks": len(world.ground_truth),
            "groundTruthTuning": tuning,
            "groundTruthHoldout": holdout,
        },
        "anomalyCounts": world.anomaly_counts,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1200, help="number of payments to generate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=_REPO_ROOT / "data" / "synthetic" / "out")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = parser.parse_args()

    world = generate_world(args.count, args.seed, lookback_days=args.lookback_days)
    inject_anomalies(world, random.Random(args.seed ^ 0x5EED))
    manifest = write_world(world, args.out)

    print(f"Wrote {args.out}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
