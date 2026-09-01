"""Indexes over a run's transactions.

Every rule is a join, and every join here is a dict lookup - built once
in O(n), queried in O(1). That is the same access pattern the SQL version
would get from a B-tree index, without a database round trip per lookup.

The performance failure this avoids is the one named in
docs/03-architecture.md P1: a rule written as a loop that issues a query
per record. At 10,000 payments that is 10,000 round trips per rule. Here
it is one pass to build, then constant-time probes.

The candidate window (P2) is the other half. `by_amount_and_date` is
keyed on the exact tuple a scored rule needs, so candidate retrieval is
never a scan and never a cross join.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import EntityType

#: Hard ceiling on candidates returned for one record. Exceeding it is
#: itself a signal of ambiguity, and it is a correctness feature as much
#: as a performance one - see docs/03-architecture.md P2.
MAX_CANDIDATES = 20


class TransactionIndex:
    """Read-only indexes over the transactions in one run."""

    __slots__ = (
        "_all", "by_id", "by_parent", "by_reference", "by_type",
        "_by_amount_date", "_consumed",
    )

    def __init__(self, transactions: Iterable[CanonicalTransaction]) -> None:
        self._all: list[CanonicalTransaction] = list(transactions)

        self.by_id: dict[str, CanonicalTransaction] = {}
        self.by_parent: dict[str, list[CanonicalTransaction]] = defaultdict(list)
        self.by_reference: dict[str, list[CanonicalTransaction]] = defaultdict(list)
        self.by_type: dict[EntityType, list[CanonicalTransaction]] = defaultdict(list)
        self._by_amount_date: dict[tuple[int, date], list[CanonicalTransaction]] = defaultdict(list)

        #: Transactions already claimed by a group. Exclusivity is enforced
        #: here the way the partial unique index enforces it in the
        #: database: without it, a bug in rule ordering counts the same
        #: money twice and flatters the reconciliation rate.
        self._consumed: set[str] = set()

        for txn in self._all:
            key = txn.external_id_norm
            # A genuine id collision is a duplicate, not an index error;
            # first write wins and the duplicate detector reports it.
            self.by_id.setdefault(key, txn)
            self.by_type[txn.entity_type].append(txn)

            if txn.parent_external_id:
                self.by_parent[txn.parent_external_id.strip().upper()].append(txn)
            if txn.reference_id:
                self.by_reference[txn.reference_id.strip().upper()].append(txn)

            self._by_amount_date[(txn.net_amount_minor, txn.business_date)].append(txn)

    # -- basic access -----------------------------------------------------

    def __len__(self) -> int:
        return len(self._all)

    @property
    def all(self) -> list[CanonicalTransaction]:
        return self._all

    def of_type(self, *types: EntityType) -> list[CanonicalTransaction]:
        out: list[CanonicalTransaction] = []
        for t in types:
            out.extend(self.by_type.get(t, ()))
        return out

    def get(self, external_id: str | None) -> CanonicalTransaction | None:
        if not external_id:
            return None
        return self.by_id.get(external_id.strip().upper())

    def children_of(self, external_id: str) -> list[CanonicalTransaction]:
        """Records naming this one as their parent - a settlement line's
        payment, a refund's original."""
        return list(self.by_parent.get(external_id.strip().upper(), ()))

    def referencing(self, reference: str | None) -> list[CanonicalTransaction]:
        """Records pointing at this identifier across systems."""
        if not reference:
            return []
        return list(self.by_reference.get(reference.strip().upper(), ()))

    # -- exclusivity ------------------------------------------------------

    def is_consumed(self, txn: CanonicalTransaction) -> bool:
        return txn.external_id_norm in self._consumed

    def consume(self, *transactions: CanonicalTransaction) -> None:
        for txn in transactions:
            self._consumed.add(txn.external_id_norm)

    def unconsumed(self, *types: EntityType) -> list[CanonicalTransaction]:
        return [t for t in self.of_type(*types) if not self.is_consumed(t)]

    # -- candidate window -------------------------------------------------

    def candidates(
        self,
        subject: CanonicalTransaction,
        *,
        entity_types: tuple[EntityType, ...],
        window_days: int,
        amount_tolerance_minor: int = 0,
        include_consumed: bool = False,
    ) -> list[CanonicalTransaction]:
        """Plausible counterparts within a bounded window.

        Bounded on every axis before anything is scored: same currency,
        amount within tolerance, business date inside the window,
        compatible entity type. An unbounded version of this is a cross
        join - 10,000 x 10,000 is not slow, it is a hang.
        """
        wanted = set(entity_types)
        out: list[CanonicalTransaction] = []

        low = subject.net_amount_minor - amount_tolerance_minor
        high = subject.net_amount_minor + amount_tolerance_minor

        for offset in range(0, window_days + 1):
            day = subject.business_date + timedelta(days=offset)
            for amount in range(low, high + 1) if amount_tolerance_minor else (low,):
                for candidate in self._by_amount_date.get((amount, day), ()):
                    if candidate.external_id_norm == subject.external_id_norm:
                        continue
                    if candidate.entity_type not in wanted:
                        continue
                    if candidate.currency != subject.currency:
                        continue
                    if not include_consumed and self.is_consumed(candidate):
                        continue
                    out.append(candidate)
                    if len(out) > MAX_CANDIDATES:
                        return out[:MAX_CANDIDATES]
        return out
