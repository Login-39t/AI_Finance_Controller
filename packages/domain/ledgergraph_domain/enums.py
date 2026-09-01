"""Controlled vocabularies.

Every enum here mirrors a `CREATE TYPE ... AS ENUM` in `db/schema.sql`,
value for value. That correspondence is not a convention to be remembered
- `tests/unit/test_enums.py` parses the SQL and asserts it, so drift
between the Python and the database fails the build rather than surfacing
as a rejected INSERT at runtime.

`StrEnum` so members compare equal to plain strings in both directions
and `str(member)` returns the value rather than `ClassName.MEMBER`. That
matters at the edges: a CSV cell, a JSON body, and a database value are
all `str`, and neither the normalisers nor a log line should have to
remember which side of a comparison needs `.value`.
"""

from __future__ import annotations

from enum import Enum, StrEnum

__all__ = [
    "ActorType",
    "AiValidationStatus",
    "CaseResolution",
    "DecisionAction",
    "EntityType",
    "ExceptionSeverity",
    "ExceptionStatus",
    "ExceptionType",
    "GroupStatus",
    "GroupType",
    "ImportStatus",
    "LinkRole",
    "RuleTier",
    "RunStatus",
    "SourceSystem",
    "TruthPartition",
    "TxnDirection",
    "TxnStatus",
    "UserRole",
]


class UserRole(StrEnum):
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    CONTROLLER = "controller"
    ADMIN = "admin"


class SourceSystem(StrEnum):
    GATEWAY_PAYMENTS = "gateway_payments"
    RAZORPAY_SETTLEMENTS = "razorpay_settlements"
    BANK_STATEMENT = "bank_statement"
    INVOICES = "invoices"
    INTERNAL_LEDGER = "internal_ledger"


class EntityType(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"
    SETTLEMENT_BATCH = "settlement_batch"
    SETTLEMENT_LINE = "settlement_line"
    BANK_TRANSACTION = "bank_transaction"
    INVOICE = "invoice"
    LEDGER_ENTRY = "ledger_entry"
    ADJUSTMENT = "adjustment"
    DISPUTE = "dispute"


class TxnDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class TxnStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    SETTLED = "settled"
    REVERSED = "reversed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    POSTED = "posted"
    PENDING = "pending"


class ImportStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GroupType(StrEnum):
    ONE_TO_ONE = "one_to_one"
    MANY_TO_ONE = "many_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_MANY = "many_to_many"


class GroupStatus(StrEnum):
    PROPOSED = "proposed"
    AUTO_RESOLVED = "auto_resolved"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class LinkRole(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"
    SETTLEMENT_BATCH = "settlement_batch"
    SETTLEMENT_LINE = "settlement_line"
    BANK_CREDIT = "bank_credit"
    BANK_DEBIT = "bank_debit"
    INVOICE = "invoice"
    LEDGER_DEBIT = "ledger_debit"
    LEDGER_CREDIT = "ledger_credit"
    FEE = "fee"
    TAX = "tax"
    ADJUSTMENT = "adjustment"
    SPLIT_COMPONENT = "split_component"


class ExceptionType(StrEnum):
    """The eight from blueprint section 10. Deliberately closed.

    The AI's `classification` field validates against exactly this set, so
    a hallucinated category cannot be stored.
    """

    UNMATCHED_PAYMENT = "unmatched_payment"
    MISSING_BANK_CREDIT = "missing_bank_credit"
    AMOUNT_MISMATCH = "amount_mismatch"
    DATE_MISMATCH = "date_mismatch"
    DUPLICATE = "duplicate"
    REFUND_UNLINKED = "refund_unlinked"
    STATUS_CONFLICT = "status_conflict"
    FEE_TAX_DISCREPANCY = "fee_tax_discrepancy"


class ExceptionSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExceptionStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    #: Not a failure. Abstention is a correct outcome when the evidence
    #: does not support a single answer (blueprint section 17).
    UNRESOLVED = "unresolved"


class CaseResolution(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    DISMISSED = "dismissed"
    AUTO_RESOLVED = "auto_resolved"


class DecisionAction(StrEnum):
    AUTO_RESOLVED = "auto_resolved"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    ASSIGNED = "assigned"
    COMMENTED = "commented"
    REOPENED = "reopened"
    DISMISSED = "dismissed"
    ROLE_CHANGED = "role_changed"
    POLICY_CHANGED = "policy_changed"
    IMPORTED = "imported"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    AI_INVESTIGATED = "ai_investigated"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    AI = "ai"


class AiValidationStatus(StrEnum):
    VALID = "valid"
    SCHEMA_INVALID = "schema_invalid"
    CITATION_VIOLATION = "citation_violation"
    NUMERIC_VIOLATION = "numeric_violation"
    UNAVAILABLE = "unavailable"


class RuleTier(StrEnum):
    DETERMINISTIC = "deterministic"
    SCORED = "scored"


class TruthPartition(StrEnum):
    TUNING = "tuning"
    HOLDOUT = "holdout"


#: Maps a Python enum to the `CREATE TYPE` name it mirrors in db/schema.sql.
#: Consumed by tests/unit/test_enums.py to assert the two never drift.
SQL_TYPE_NAMES: dict[type[Enum], str] = {
    UserRole: "user_role",
    SourceSystem: "source_system",
    EntityType: "entity_type",
    TxnDirection: "txn_direction",
    TxnStatus: "txn_status",
    ImportStatus: "import_status",
    RunStatus: "run_status",
    GroupType: "group_type",
    GroupStatus: "group_status",
    LinkRole: "link_role",
    ExceptionType: "exception_type",
    ExceptionSeverity: "exception_severity",
    ExceptionStatus: "exception_status",
    CaseResolution: "case_resolution",
    DecisionAction: "decision_action",
    ActorType: "actor_type",
    AiValidationStatus: "ai_validation_status",
    RuleTier: "rule_tier",
    TruthPartition: "truth_partition",
}
