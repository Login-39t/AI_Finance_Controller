"""Result shapes the engine produces.

These mirror `reconciliation_groups`, `reconciliation_links`,
`reconciliation_evidence`, and `exception_cases` in `db/schema.sql`. The
engine builds them in memory; persisting them is the API's job, and
keeping that boundary means the evaluation harness can run the real
engine without a database.

Money is `int` minor units throughout, as everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import (
    ExceptionSeverity,
    ExceptionType,
    GroupStatus,
    GroupType,
    LinkRole,
    RuleTier,
)


@dataclass(frozen=True, slots=True)
class Evidence:
    """Why a rule fired, with the values it actually compared.

    `computed` holds the operands, not a summary of them. A group cannot
    reach a resolved status without at least one passing evidence row -
    the same rule the database enforces with a constraint trigger.
    """

    rule_code: str
    evidence_type: str
    statement: str
    computed: dict[str, str]
    passed: bool


@dataclass(frozen=True, slots=True)
class BridgeComponent:
    label: str
    amount_minor: int
    operation: str            # "base" | "subtract" | "add"
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class Bridge:
    """gross - refunds - fees - taxes +/- adjustments = net.

    `difference_minor` is signed and always shown, including when it is
    zero. Tolerance consumed is reported rather than absorbed silently -
    a bridge that balances only by spending its tolerance is a different
    fact from one that balances exactly.
    """

    currency: str
    components: tuple[BridgeComponent, ...]
    expected_net_minor: int
    observed_net_minor: int
    tolerance_minor: int

    @property
    def difference_minor(self) -> int:
        return self.observed_net_minor - self.expected_net_minor

    @property
    def balances(self) -> bool:
        return abs(self.difference_minor) <= self.tolerance_minor

    @property
    def balances_exactly(self) -> bool:
        return self.difference_minor == 0

    @property
    def tolerance_consumed_minor(self) -> int:
        return abs(self.difference_minor) if self.balances else 0


@dataclass(frozen=True, slots=True)
class Link:
    """One transaction's membership in a group."""

    transaction: CanonicalTransaction
    role: LinkRole
    matched_amount_minor: int


@dataclass(frozen=True, slots=True)
class GateCondition:
    key: str
    label: str
    passed: bool
    detail: str


@dataclass(slots=True)
class MatchGroup:
    """A proposed reconciliation, and everything needed to defend it."""

    group_id: str
    group_type: GroupType
    matched_by_rule: str
    tier: RuleTier
    links: list[Link] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    bridge: Bridge | None = None
    confidence: float = 0.0
    confidence_components: dict[str, float] = field(default_factory=dict)
    gate: list[GateCondition] = field(default_factory=list)
    status: GroupStatus = GroupStatus.PROPOSED
    explanation: str = ""

    @property
    def transaction_ids(self) -> set[str]:
        return {link.transaction.external_id_norm for link in self.links}

    @property
    def total_amount_minor(self) -> int:
        return max((link.matched_amount_minor for link in self.links), default=0)

    @property
    def currency(self) -> str:
        return self.links[0].transaction.currency if self.links else "INR"

    @property
    def auto_resolved(self) -> bool:
        return self.status is GroupStatus.AUTO_RESOLVED

    def role_of(self, role: LinkRole) -> list[CanonicalTransaction]:
        return [link.transaction for link in self.links if link.role is role]

    def has_passing_evidence(self) -> bool:
        return any(e.passed for e in self.evidence)


@dataclass(slots=True)
class ExceptionCase:
    """A finding routed to a human, sorted by money at risk."""

    case_id: str
    case_type: ExceptionType
    severity: ExceptionSeverity
    amount_at_risk_minor: int
    currency: str
    primary_transaction: CanonicalTransaction | None
    transactions: list[CanonicalTransaction] = field(default_factory=list)
    group: MatchGroup | None = None
    hypothesis: str = ""
    recommendation: str = ""
    confidence: float | None = None
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def primary_external_id(self) -> str:
        if self.primary_transaction is not None:
            return self.primary_transaction.external_id
        return self.case_id


@dataclass(slots=True)
class RunResult:
    """Everything one reconciliation run produced."""

    run_id: str
    ruleset_version: str
    groups: list[MatchGroup] = field(default_factory=list)
    cases: list[ExceptionCase] = field(default_factory=list)
    stage_timings_ms: dict[str, int] = field(default_factory=dict)
    records_processed: int = 0

    @property
    def auto_resolved(self) -> list[MatchGroup]:
        return [g for g in self.groups if g.status is GroupStatus.AUTO_RESOLVED]

    @property
    def pending_review(self) -> list[MatchGroup]:
        return [g for g in self.groups if g.status is GroupStatus.PENDING_REVIEW]

    def summary(self) -> dict[str, int]:
        return {
            "records_processed": self.records_processed,
            "groups": len(self.groups),
            "auto_resolved": len(self.auto_resolved),
            "pending_review": len(self.pending_review),
            "exceptions": len(self.cases),
        }
