# Synthetic dataset generator

Produces five source files that look like real exports, plus a ground
truth file recording what should link across them.

```bash
python -m data.synthetic.generator --count 1200 --seed 42
```

Writes to `data/synthetic/out/` (gitignored - regenerate, don't commit):

| File | Source system | Rows describe |
|---|---|---|
| `payments.csv` | `gateway_payments` | Payments and refunds (`record_type` column distinguishes them) |
| `settlement_batches.csv` | `razorpay_settlements` | Daily payout batches: gross, fee, tax, net, UTR |
| `settlement_lines.csv` | `razorpay_settlements` | Per-payment lines within a batch |
| `bank_statement.csv` | `bank_statement` | Bank credits for each settlement |
| `invoices.csv` | `invoices` | Order-level due/paid amounts |
| `ledger.csv` | `internal_ledger` | Double-entry postings per batch (bank, fee, GST, revenue) |
| `ground_truth.json` | — | The truth: which IDs *should* link, and which anomaly (if any) was injected |
| `manifest.json` | — | Seed, fee schedule, counts per file, counts per anomaly type |

## Determinism

Same `--seed` → byte-identical files, always. There's no `date.today()`
anywhere in the generator - the dataset's end date is a fixed anchor
(`2026-03-04`), so re-running next month produces the same thing.
`assign_partition()` hashes `(seed, truth_id)`, not generation order, so
the tuning/holdout split can't drift if a rule change alters which
records get created first.

## The twelve anomalies

Each is a real, structurally-consistent defect - never a row that would
fail ingestion outright. `ground_truth.json` labels every affected record
with `injectedAnomaly`, so the eval harness can report recall per anomaly
type instead of one number that hides which defects the engine actually
catches.

| Anomaly | Exception type | What's broken |
|---|---|---|
| `delayed_settlement` | `date_mismatch` | Settles T+4..T+6, outside the window. Amounts exact. |
| `missing_settlement_line` | `unmatched_payment` | One line silently dropped from a multi-line batch. |
| `missing_bank_credit_single` | `missing_bank_credit` | UTR blanked; exactly one bank credit matches by amount+date. |
| `missing_bank_credit_ambiguous` | `missing_bank_credit` | Same, plus a second, unrelated credit for the identical amount - the flagship abstention case. |
| `duplicate_bank_row` | `duplicate` | A bank credit presented twice under different `bank_txn_id`s. |
| `duplicate_ledger_entry` | `duplicate` | A revenue line posted twice under different `journal_id`s. |
| `wrong_fee_mapping` | `fee_tax_discrepancy` | Batch charged at a rate that matches no method in the fee schedule - internally consistent, policy-inconsistent. |
| `wrong_ledger_amount` | `amount_mismatch` | Revenue posted net of GST on the fee; `Σdebits ≠ Σcredits` by exactly the tax amount. |
| `refund_unlinked` | `refund_unlinked` | The refund's parent payment is not in this dataset at all. |
| `status_conflict` | `status_conflict` | Gateway says captured; invoice still says unpaid. |
| `reference_truncated` | (still matchable) | UTR truncated in the bank narration - exercises prefix-plus-corroboration matching, not abstention. |

Two edge cases from PRD §6.2 are baked into the *population*, not the
injector, since they're timing-correctness traps rather than labeled
defects: a few payments captured at 23:5x IST (settlement must run off
the IST business date, not the UTC instant), and ~5% of timestamps with
no timezone offset at all (normalisation must assume `Asia/Kolkata` and
record that it did).

## Fair allocation across a scarce resource

Nine of the twelve injectors compete for the same pool of settlement
batches - and batches are a daily aggregate, not a per-payment one, so
there are far fewer of them than payments. Sizing each injector's target
off the payment count (as if batches were as plentiful) starves whichever
injector runs last: at the original default (400 payments, 12 batches),
the first two injectors in line claimed every batch and five entire
anomaly types silently produced zero instances - passed without error,
wrong on close inspection. `_batch_target_count()` divides the actual
batch supply across the nine competitors instead, and `test_every_anomaly_type_fires_at_least_once`
in `tests/unit/test_synthetic_generator.py` exists specifically so that
regression can't come back unnoticed.

## Regenerating and checking your work

```bash
make gen-data                 # writes data/synthetic/out/
pytest tests/unit/test_synthetic_generator.py -v
```

The test suite checks more than "it ran": every arithmetic identity holds
except where an anomaly deliberately breaks it, every anomaly type
produces at least one instance, the flagship ambiguous case genuinely has
two competing candidates, and the same seed reproduces byte-identical
output.
