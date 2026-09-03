"""SQLAlchemy Core tables, mirroring `db/schema.sql`.

**`db/schema.sql` is the source of truth; this file follows it.** Nothing
here creates anything — `metadata.create_all()` is never called, and
migrations apply the SQL file verbatim. These definitions exist so
queries can be written in Core rather than as f-strings, which is what
makes parameter binding automatic and a typo a Python error rather than a
runtime `UndefinedColumn`.

Only the columns the repository actually reads or writes are declared.
That is a deliberate subset, not an oversight: a Core table that lists
every column would have to be kept in step with the schema by hand for no
benefit, since Core never issues `SELECT *`. `tests/unit/test_tables.py`
asserts that every table and column named here exists in `db/schema.sql`,
so the subset cannot drift into fiction.

Enums are declared with `create_type=False`. The types already exist —
the schema created them — and letting SQLAlchemy try to create them again
turns every insert into a failed `CREATE TYPE`.
"""

from __future__ import annotations

from ledgergraph_domain import enums
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

metadata = MetaData()


#: Schema enum name -> the domain StrEnum that carries its labels. The
#: labels have to be handed to SQLAlchemy for a read to work at all: an
#: `ENUM(name=..., create_type=False)` with no members has an empty
#: allow-list, so its result processor rejects every value it reads back
#: ("not among the defined enum values … Possible values: None"). The
#: domain enums are the single source for these labels and are checked
#: against `db/schema.sql` by `tests/unit/test_enums.py`, so this mapping
#: cannot silently drift from the database.
_ENUM_SOURCE: dict[str, type[enums.StrEnum]] = {
    "actor_type": enums.ActorType,
    "ai_validation_status": enums.AiValidationStatus,
    "case_resolution": enums.CaseResolution,
    "decision_action": enums.DecisionAction,
    "entity_type": enums.EntityType,
    "exception_severity": enums.ExceptionSeverity,
    "exception_status": enums.ExceptionStatus,
    "exception_type": enums.ExceptionType,
    "group_status": enums.GroupStatus,
    "group_type": enums.GroupType,
    "import_status": enums.ImportStatus,
    "link_role": enums.LinkRole,
    "rule_tier": enums.RuleTier,
    "run_status": enums.RunStatus,
    "source_system": enums.SourceSystem,
    "txn_direction": enums.TxnDirection,
    "txn_status": enums.TxnStatus,
    "user_role": enums.UserRole,
}


def _enum(name: str) -> ENUM:
    """A Postgres enum the schema already created.

    `create_type=False` because `db/schema.sql` owns the type; SQLAlchemy
    must not try to `CREATE TYPE` it again. The labels are passed as plain
    strings (not the Python enum class) so a read returns the string the
    repository expects and re-wraps itself (``UserRole(row["role"])``),
    while a write still goes through the native enum and Postgres enforces
    the value.
    """
    return ENUM(*(m.value for m in _ENUM_SOURCE[name]),
                name=name, create_type=False)


def _uuid() -> UUID:
    return UUID(as_uuid=True)


organizations = Table(
    "organizations", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("name", Text, nullable=False),
    Column("business_timezone", Text, nullable=False),
    Column("base_currency", Text, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

policies = Table(
    "policies", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("version", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("auto_resolve_min_confidence", Numeric(5, 4), nullable=False),
    Column("auto_resolve_max_minor", BigInteger, nullable=False),
    Column("review_required_above_minor", BigInteger, nullable=False),
    Column("candidate_margin", Numeric(5, 4), nullable=False),
    Column("settlement_window_days", Integer, nullable=False),
    Column("amount_tolerance_minor", BigInteger, nullable=False),
)

users = Table(
    "users", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    # CITEXT in the schema; Text here. SQLAlchemy sends a string either
    # way and the column's own collation does the case-insensitive
    # comparison, so declaring the extension type buys nothing.
    Column("email", Text, nullable=False),
    Column("hashed_password", Text, nullable=False),
    Column("full_name", Text),
    Column("role", _enum("user_role"), nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("is_verified", Boolean, nullable=False),
    Column("last_login_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)

refresh_tokens = Table(
    "refresh_tokens", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("user_id", _uuid(), nullable=False),
    Column("token_hash", Text, nullable=False),
    Column("family_id", _uuid(), nullable=False),
    Column("issued_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

source_files = Table(
    "source_files", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("source_system", _enum("source_system"), nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("content_type", Text),
    Column("byte_size", BigInteger, nullable=False),
    Column("file_sha256", Text, nullable=False),
    Column("raw_bytes", Text),
    Column("storage_uri", Text),
    Column("uploaded_by", _uuid()),
    Column("uploaded_at", DateTime(timezone=True)),
)

imports = Table(
    "imports", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("source_file_id", _uuid(), nullable=False),
    Column("source_system", _enum("source_system"), nullable=False),
    Column("idempotency_key", Text),
    Column("status", _enum("import_status"), nullable=False),
    Column("rows_total", Integer, nullable=False),
    Column("rows_accepted", Integer, nullable=False),
    Column("rows_rejected", Integer, nullable=False),
    Column("error", Text),
    Column("created_by", _uuid()),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
)

import_rejections = Table(
    "import_rejections", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("import_id", _uuid(), nullable=False),
    Column("row_number", Integer, nullable=False),
    Column("column_name", Text),
    Column("raw_value", Text),
    Column("error_code", Text, nullable=False),
    Column("error_message", Text, nullable=False),
    Column("raw_row", JSONB, nullable=False),
)

source_records = Table(
    "source_records", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("import_id", _uuid(), nullable=False),
    Column("source_file_id", _uuid(), nullable=False),
    Column("source_system", _enum("source_system"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("row_number", Integer, nullable=False),
    Column("raw_payload", JSONB, nullable=False),
    Column("row_hash", Text, nullable=False),
)

canonical_transactions = Table(
    "canonical_transactions", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("source_record_id", _uuid(), nullable=False),
    Column("entity_type", _enum("entity_type"), nullable=False),
    Column("source_system", _enum("source_system"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("external_id_norm", Text, nullable=False),
    Column("parent_external_id", Text),
    Column("reference_id", Text),
    Column("customer_ref", Text),
    Column("currency", Text, nullable=False),
    Column("gross_amount_minor", BigInteger, nullable=False),
    Column("fee_amount_minor", BigInteger, nullable=False),
    Column("tax_amount_minor", BigInteger, nullable=False),
    Column("net_amount_minor", BigInteger, nullable=False),
    Column("direction", _enum("txn_direction"), nullable=False),
    Column("status", _enum("txn_status"), nullable=False),
    Column("event_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True)),
    Column("business_date", Date, nullable=False),
    Column("business_timezone", Text, nullable=False),
    Column("tz_assumed", Boolean, nullable=False),
    Column("counterparty", Text),
    Column("description", Text),
    Column("metadata", JSONB, nullable=False),
    Column("data_quality_flags", ARRAY(Text), nullable=False),
)

dataset_snapshots = Table(
    "dataset_snapshots", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("name", Text, nullable=False),
    Column("date_from", Date, nullable=False),
    Column("date_to", Date, nullable=False),
    Column("source_systems", ARRAY(_enum("source_system")), nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("snapshot_hash", Text, nullable=False),
)

reconciliation_runs = Table(
    "reconciliation_runs", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("snapshot_id", _uuid(), nullable=False),
    Column("policy_id", _uuid(), nullable=False),
    Column("ruleset_version", Text, nullable=False),
    Column("status", _enum("run_status"), nullable=False),
    Column("current_stage", Text),
    Column("progress_pct", SmallInteger, nullable=False),
    Column("error", Text),
    Column("failed_stage", Text),
    Column("triggered_by", _uuid()),
    Column("queued_at", DateTime(timezone=True)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
)

run_metrics = Table(
    "run_metrics", metadata,
    Column("run_id", _uuid(), primary_key=True),
    Column("records_processed", Integer, nullable=False),
    Column("records_auto_resolved", Integer, nullable=False),
    Column("records_pending_review", Integer, nullable=False),
    Column("records_unresolved", Integer, nullable=False),
    Column("gross_processed_minor", BigInteger, nullable=False),
    Column("unresolved_value_minor", BigInteger, nullable=False),
    Column("groups_created", Integer, nullable=False),
    Column("exceptions_created", Integer, nullable=False),
    Column("duration_ms", Integer),
    Column("stage_timings", JSONB, nullable=False),
)

reconciliation_groups = Table(
    "reconciliation_groups", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("run_id", _uuid(), nullable=False),
    Column("org_id", _uuid(), nullable=False),
    Column("group_type", _enum("group_type"), nullable=False),
    Column("status", _enum("group_status"), nullable=False),
    Column("matched_by_rule", Text, nullable=False),
    Column("tier", _enum("rule_tier"), nullable=False),
    Column("confidence", Numeric(5, 4), nullable=False),
    Column("confidence_components", JSONB, nullable=False),
    Column("gate_result", JSONB, nullable=False),
    Column("bridge", JSONB),
    Column("total_amount_minor", BigInteger, nullable=False),
    Column("currency", Text, nullable=False),
    Column("explanation", Text),
    Column("auto_resolved", Boolean, nullable=False),
    Column("ruleset_version", Text, nullable=False),
    Column("policy_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

reconciliation_links = Table(
    "reconciliation_links", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("group_id", _uuid(), nullable=False),
    Column("run_id", _uuid(), nullable=False),
    Column("transaction_id", _uuid(), nullable=False),
    Column("role", _enum("link_role"), nullable=False),
    Column("matched_amount_minor", BigInteger, nullable=False),
    Column("evidence_json", JSONB, nullable=False),
)

reconciliation_evidence = Table(
    "reconciliation_evidence", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("group_id", _uuid(), nullable=False),
    Column("rule_code", Text, nullable=False),
    Column("evidence_type", Text, nullable=False),
    Column("statement", Text, nullable=False),
    Column("computed", JSONB, nullable=False),
    Column("passed", Boolean, nullable=False),
)

exception_cases = Table(
    "exception_cases", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("run_id", _uuid(), nullable=False),
    Column("org_id", _uuid(), nullable=False),
    Column("group_id", _uuid()),
    Column("primary_transaction_id", _uuid()),
    Column("case_type", _enum("exception_type"), nullable=False),
    Column("severity", _enum("exception_severity"), nullable=False),
    Column("status", _enum("exception_status"), nullable=False),
    Column("amount_at_risk_minor", BigInteger, nullable=False),
    Column("currency", Text, nullable=False),
    Column("hypothesis", Text),
    Column("recommendation", Text),
    Column("confidence", Numeric(5, 4)),
    Column("assigned_to", _uuid()),
    Column("opened_at", DateTime(timezone=True)),
    Column("resolved_at", DateTime(timezone=True)),
    Column("resolved_by", _uuid()),
    Column("resolution", _enum("case_resolution")),
    Column("resolution_reason_code", Text),
    Column("resolution_note", Text),
)

exception_case_transactions = Table(
    "exception_case_transactions", metadata,
    Column("case_id", _uuid(), primary_key=True),
    Column("transaction_id", _uuid(), primary_key=True),
    Column("role", Text, nullable=False),
)

ai_investigations = Table(
    "ai_investigations", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("case_id", _uuid(), nullable=False),
    Column("model_version", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("packet_hash", Text, nullable=False),
    Column("validation_status", _enum("ai_validation_status"), nullable=False),
    Column("validation_errors", JSONB, nullable=False),
    Column("classification", _enum("exception_type")),
    Column("hypotheses", JSONB, nullable=False),
    Column("recommended_action", Text),
    Column("requires_human_approval", Boolean),
    Column("confidence", Numeric(5, 4)),
    Column("uncertainties", JSONB, nullable=False),
    Column("cited_evidence_ids", ARRAY(Text), nullable=False),
    Column("latency_ms", Integer),
    Column("created_at", DateTime(timezone=True)),
)

decision_audit_events = Table(
    "decision_audit_events", metadata,
    Column("id", _uuid(), primary_key=True),
    Column("org_id", _uuid(), nullable=False),
    Column("entity_type", Text, nullable=False),
    Column("entity_id", _uuid(), nullable=False),
    Column("action", _enum("decision_action"), nullable=False),
    Column("actor_type", _enum("actor_type"), nullable=False),
    Column("actor_id", _uuid()),
    Column("actor_role", _enum("user_role")),
    Column("reason_code", Text),
    Column("ruleset_version", Text),
    Column("model_version", Text),
    Column("payload_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)
