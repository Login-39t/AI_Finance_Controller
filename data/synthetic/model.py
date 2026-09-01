"""Record shapes shared by `generator.py` (population) and `anomalies.py`
(injection).

Split into its own module so the two can import each other's target types
without a circular import - `generator.py` calls `inject_anomalies()`, and
`anomalies.py` needs to construct and mutate `Payment`, `SettlementBatch`,
and friends.

Every amount field is `*_minor` - an `int` in paise, never a float or a
pre-formatted string. Conversion to the decimal string a CSV actually
holds happens once, in each dataclass's `row()`, via the same
`format_minor` the frontend and ingestion layer use - so every arithmetic
identity here is exact by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ledgergraph_domain.money import format_minor

CURRENCY = "INR"


@dataclass
class Payment:
    payment_id: str
    order_id: str
    amount_minor: int
    currency: str
    status: str
    created_at: str
    method: str
    record_type: str = "payment"       # 'payment' | 'refund'
    parent_payment_id: str = ""

    def row(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "amount": format_minor(self.amount_minor, self.currency, symbol=False),
            "currency": self.currency,
            "status": self.status,
            "created_at": self.created_at,
            "method": self.method,
            "record_type": self.record_type,
            "parent_payment_id": self.parent_payment_id,
        }


@dataclass
class SettlementBatch:
    batch_id: str
    gross_minor: int
    fee_minor: int
    tax_minor: int
    net_minor: int
    status: str
    settled_at: str
    payout_utr: str = ""

    def row(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "gross": format_minor(self.gross_minor, CURRENCY, symbol=False),
            "fee": format_minor(self.fee_minor, CURRENCY, symbol=False),
            "tax": format_minor(self.tax_minor, CURRENCY, symbol=False),
            "net": format_minor(self.net_minor, CURRENCY, symbol=False),
            "status": self.status,
            "settled_at": self.settled_at,
            "payout_utr": self.payout_utr,
        }


@dataclass
class SettlementLine:
    settlement_id: str
    batch_id: str
    payment_id: str
    gross_minor: int
    fee_minor: int
    tax_minor: int
    net_minor: int

    def row(self) -> dict:
        return {
            "settlement_id": self.settlement_id,
            "batch_id": self.batch_id,
            "payment_id": self.payment_id,
            "gross": format_minor(self.gross_minor, CURRENCY, symbol=False),
            "fee": format_minor(self.fee_minor, CURRENCY, symbol=False),
            "tax": format_minor(self.tax_minor, CURRENCY, symbol=False),
            "net": format_minor(self.net_minor, CURRENCY, symbol=False),
        }


@dataclass
class BankTxn:
    bank_txn_id: str
    txn_date: str          # date-only, the way a bank statement export gives it
    amount_minor: int
    direction: str
    reference: str
    description: str
    balance_minor: int

    def row(self) -> dict:
        return {
            "bank_txn_id": self.bank_txn_id,
            "date": self.txn_date,
            "amount": format_minor(self.amount_minor, CURRENCY, symbol=False),
            "direction": self.direction,
            "reference": self.reference,
            "description": self.description,
            "balance": format_minor(self.balance_minor, CURRENCY, symbol=False),
        }


@dataclass
class Invoice:
    invoice_id: str
    order_id: str
    customer_ref: str
    amount_due_minor: int
    amount_paid_minor: int
    status: str
    issued_at: str

    def row(self) -> dict:
        return {
            "invoice_id": self.invoice_id,
            "order_id": self.order_id,
            "customer_id": self.customer_ref,
            "amount_due": format_minor(self.amount_due_minor, CURRENCY, symbol=False),
            "amount_paid": format_minor(self.amount_paid_minor, CURRENCY, symbol=False),
            "status": self.status,
            "issued_at": self.issued_at,
        }


@dataclass
class LedgerEntry:
    journal_id: str
    account: str
    debit_minor: int
    credit_minor: int
    reference: str
    posted_at: str
    status: str = "posted"

    def row(self) -> dict:
        return {
            "journal_id": self.journal_id,
            "account": self.account,
            "debit": format_minor(self.debit_minor, CURRENCY, symbol=False),
            "credit": format_minor(self.credit_minor, CURRENCY, symbol=False),
            "reference": self.reference,
            "posted_at": self.posted_at,
            "status": self.status,
        }


@dataclass
class World:
    """Everything the generator produced, in one container.

    `anomalies.py` mutates these lists in place and appends to
    `ground_truth`; nothing is written to disk until every mutation has
    happened, so the files on disk and the ground truth describing them
    are never out of sync.
    """

    seed: int
    end_date: date
    payments: list[Payment] = field(default_factory=list)
    batches: list[SettlementBatch] = field(default_factory=list)
    lines: list[SettlementLine] = field(default_factory=list)
    bank: list[BankTxn] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    ledger: list[LedgerEntry] = field(default_factory=list)
    ground_truth: list[dict] = field(default_factory=list)
    anomaly_counts: dict[str, int] = field(default_factory=dict)

    def lines_for_batch(self, batch_id: str) -> list[SettlementLine]:
        return [ln for ln in self.lines if ln.batch_id == batch_id]

    def ledger_for_batch(self, batch_id: str) -> list[LedgerEntry]:
        return [e for e in self.ledger if e.reference == batch_id]

    def ground_truth_for_batch(self, batch_id: str) -> list[dict]:
        return [g for g in self.ground_truth if batch_id in g["externalIds"]]
