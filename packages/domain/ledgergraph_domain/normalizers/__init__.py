"""Per-source normalisers, and the registry that selects one.

Selection is by *declared* dataset, never sniffed from the file's
contents. FR-1 requires the caller to state which source a file is, and
guessing would mean a mislabelled upload gets parsed by the wrong
normaliser and produces confidently wrong canonical records rather than
an error.
"""

from __future__ import annotations

from .bank import BankStatementNormalizer
from .base import (
    DEFAULT_BUSINESS_TZ,
    Normalizer,
    RejectionError,
    extract_reference,
    parse_instant,
)
from .invoices import InvoicesNormalizer
from .ledger import LedgerNormalizer
from .payments import PaymentsNormalizer
from .settlements import SettlementBatchNormalizer, SettlementLineNormalizer

__all__ = [
    "DEFAULT_BUSINESS_TZ",
    "NORMALIZERS",
    "BankStatementNormalizer",
    "InvoicesNormalizer",
    "LedgerNormalizer",
    "Normalizer",
    "PaymentsNormalizer",
    "RejectionError",
    "SettlementBatchNormalizer",
    "SettlementLineNormalizer",
    "extract_reference",
    "get_normalizer",
    "parse_instant",
]

NORMALIZERS: dict[str, Normalizer] = {
    n.dataset: n
    for n in (
        PaymentsNormalizer(),
        SettlementBatchNormalizer(),
        SettlementLineNormalizer(),
        BankStatementNormalizer(),
        InvoicesNormalizer(),
        LedgerNormalizer(),
    )
}


def get_normalizer(dataset: str) -> Normalizer:
    """Look up a normaliser by dataset name.

    An unknown dataset raises rather than defaulting, so a typo in an
    upload's declared type fails at the boundary.
    """
    try:
        return NORMALIZERS[dataset]
    except KeyError:
        raise RejectionError(
            "UNKNOWN_DATASET",
            f"{dataset!r} is not a known dataset; expected one of {sorted(NORMALIZERS)}",
            column="dataset",
            value=dataset,
        ) from None
