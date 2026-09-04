-- =====================================================================
-- TallyProof — PostgreSQL 16 schema
-- Reference DDL. Applied in the repo via Alembic; runnable as-is for a
-- scratch database:  psql -d ledgergraph -f db/schema.sql
--
-- Conventions
--   * All money is BIGINT minor units (paise). No float, no NUMERIC money.
--   * Sign is carried by `direction`, never by an amount.
--   * IDs are UUID; the app supplies UUIDv7 for index locality,
--     gen_random_uuid() (v4) is the fallback default.
--   * Timestamps are TIMESTAMPTZ (UTC). business_date is a stored DATE.
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email

-- =====================================================================
-- 1. ENUMERATED TYPES
-- =====================================================================

CREATE TYPE user_role AS ENUM ('analyst', 'reviewer', 'controller', 'admin');

CREATE TYPE source_system AS ENUM (
    'gateway_payments', 'razorpay_settlements', 'bank_statement',
    'invoices', 'internal_ledger'
);

CREATE TYPE entity_type AS ENUM (
    'payment', 'refund', 'settlement_batch', 'settlement_line',
    'bank_transaction', 'invoice', 'ledger_entry', 'adjustment', 'dispute'
);

CREATE TYPE txn_direction AS ENUM ('credit', 'debit');

CREATE TYPE txn_status AS ENUM (
    'created', 'authorized', 'captured', 'failed', 'refunded',
    'partially_refunded', 'settled', 'reversed', 'disputed',
    'cancelled', 'posted', 'pending'
);

CREATE TYPE import_status AS ENUM (
    'pending', 'validating', 'completed', 'failed', 'duplicate'
);

CREATE TYPE run_status AS ENUM (
    'queued', 'running', 'completed', 'failed', 'cancelled'
);

CREATE TYPE group_type AS ENUM (
    'one_to_one', 'many_to_one', 'one_to_many', 'many_to_many'
);

CREATE TYPE group_status AS ENUM (
    'proposed', 'auto_resolved', 'pending_review',
    'approved', 'rejected', 'superseded'
);

CREATE TYPE link_role AS ENUM (
    'payment', 'refund', 'settlement_batch', 'settlement_line',
    'bank_credit', 'bank_debit', 'invoice', 'ledger_debit', 'ledger_credit',
    'fee', 'tax', 'adjustment', 'split_component'
);

CREATE TYPE exception_type AS ENUM (
    'unmatched_payment', 'missing_bank_credit', 'amount_mismatch',
    'date_mismatch', 'duplicate', 'refund_unlinked',
    'status_conflict', 'fee_tax_discrepancy'
);

CREATE TYPE exception_severity AS ENUM ('critical', 'high', 'medium', 'low');

CREATE TYPE exception_status AS ENUM (
    'open', 'investigating', 'pending_approval',
    'resolved', 'dismissed', 'unresolved'
);

CREATE TYPE case_resolution AS ENUM (
    'approved', 'rejected', 'overridden', 'dismissed', 'auto_resolved'
);

CREATE TYPE decision_action AS ENUM (
    'auto_resolved', 'approved', 'rejected', 'overridden', 'assigned',
    'commented', 'reopened', 'dismissed', 'role_changed', 'policy_changed',
    'imported', 'run_started', 'run_completed', 'ai_investigated',
    -- Account lifecycle, also recorded in the one audit table.
    'registered', 'refresh_reuse_detected', 'deactivated'
);

CREATE TYPE actor_type AS ENUM ('user', 'system', 'ai');

CREATE TYPE ai_validation_status AS ENUM (
    'valid', 'schema_invalid', 'citation_violation',
    'numeric_violation', 'unavailable'
);

CREATE TYPE rule_tier AS ENUM ('deterministic', 'scored');

CREATE TYPE truth_partition AS ENUM ('tuning', 'holdout');

-- =====================================================================
-- 2. TENANCY, IDENTITY, POLICY
-- =====================================================================

CREATE TABLE organizations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              TEXT        NOT NULL,
    business_timezone TEXT        NOT NULL DEFAULT 'Asia/Kolkata',
    base_currency     CHAR(3)     NOT NULL DEFAULT 'INR',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_org_currency CHECK (base_currency ~ '^[A-Z]{3}$')
);

-- Column set is fastapi-users compatible (email, hashed_password,
-- is_active, is_superuser, is_verified) plus role and tenancy.
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    email           CITEXT      NOT NULL,
    hashed_password TEXT        NOT NULL,
    full_name       TEXT,
    role            user_role   NOT NULL DEFAULT 'analyst',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    is_verified     BOOLEAN     NOT NULL DEFAULT FALSE,
    is_superuser    BOOLEAN     NOT NULL DEFAULT FALSE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_email UNIQUE (email)
);
CREATE INDEX ix_users_org ON users (org_id);

-- Refresh tokens: hashed at rest, rotated on use, family revoked on reuse.
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL,
    family_id   UUID        NOT NULL,
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    user_agent  TEXT,
    ip_address  INET,
    CONSTRAINT uq_refresh_hash UNIQUE (token_hash)
);
CREATE INDEX ix_refresh_active ON refresh_tokens (user_id)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;
CREATE INDEX ix_refresh_family ON refresh_tokens (family_id);

-- Policy thresholds are DATA, not code. Changing one is auditable.
CREATE TABLE policies (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                      UUID          NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    version                     INTEGER       NOT NULL,
    name                        TEXT          NOT NULL,
    is_active                   BOOLEAN       NOT NULL DEFAULT FALSE,
    auto_resolve_min_confidence NUMERIC(5,4)  NOT NULL DEFAULT 0.9500,
    auto_resolve_max_minor      BIGINT        NOT NULL DEFAULT 5000000,     -- Rs 50,000
    review_required_above_minor BIGINT        NOT NULL DEFAULT 25000000,    -- Rs 2,50,000
    candidate_margin            NUMERIC(5,4)  NOT NULL DEFAULT 0.0500,
    settlement_window_days      INTEGER       NOT NULL DEFAULT 3,
    amount_tolerance_minor      BIGINT        NOT NULL DEFAULT 100,         -- Rs 1.00
    never_auto_resolve          exception_type[] NOT NULL
        DEFAULT ARRAY['duplicate','missing_bank_credit','amount_mismatch']::exception_type[],
    max_candidates_per_record   INTEGER       NOT NULL DEFAULT 20,
    created_by                  UUID REFERENCES users(id),
    created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_policy_version UNIQUE (org_id, version),
    CONSTRAINT ck_policy_conf    CHECK (auto_resolve_min_confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_policy_margin  CHECK (candidate_margin BETWEEN 0 AND 1),
    CONSTRAINT ck_policy_amounts CHECK (auto_resolve_max_minor >= 0
                                    AND review_required_above_minor >= 0
                                    AND amount_tolerance_minor >= 0),
    CONSTRAINT ck_policy_window  CHECK (settlement_window_days BETWEEN 0 AND 30)
);
-- Exactly one active policy per organisation.
CREATE UNIQUE INDEX uq_policy_active ON policies (org_id) WHERE is_active;

-- Gateway fee schedule, so fee expectations are config rather than magic numbers.
CREATE TABLE fee_schedules (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID          NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    method           TEXT          NOT NULL,          -- 'default', 'upi', 'card', 'netbanking', ...
    fee_bps          INTEGER       NOT NULL,          -- basis points, e.g. 200 = 2.00%
    fee_flat_minor   BIGINT        NOT NULL DEFAULT 0,
    tax_bps_on_fee   INTEGER       NOT NULL DEFAULT 1800,   -- 18% GST on the fee
    effective_from   DATE          NOT NULL,
    effective_to     DATE,
    CONSTRAINT uq_fee_method UNIQUE (org_id, method, effective_from),
    CONSTRAINT ck_fee_bps    CHECK (fee_bps >= 0 AND tax_bps_on_fee >= 0),
    CONSTRAINT ck_fee_dates  CHECK (effective_to IS NULL OR effective_to > effective_from)
);

-- =====================================================================
-- 3. IMMUTABLE SOURCE LAYER  (insert once; never updated)
-- =====================================================================

CREATE TABLE source_files (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            UUID          NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_system     source_system NOT NULL,
    original_filename TEXT          NOT NULL,
    content_type      TEXT,
    byte_size         BIGINT        NOT NULL,
    file_sha256       TEXT          NOT NULL,
    encoding          TEXT,
    delimiter         TEXT,
    -- Raw bytes live here behind the ObjectStore interface; swap to S3 by
    -- setting storage_uri and leaving raw_bytes NULL. See docs/02-tech-stack.md.
    raw_bytes         BYTEA,
    storage_uri       TEXT,
    uploaded_by       UUID REFERENCES users(id),
    uploaded_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_file_sha     UNIQUE (org_id, file_sha256),
    CONSTRAINT ck_file_size    CHECK (byte_size > 0),
    CONSTRAINT ck_file_storage CHECK (raw_bytes IS NOT NULL OR storage_uri IS NOT NULL)
);

CREATE TABLE imports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID          NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_file_id  UUID          NOT NULL REFERENCES source_files(id) ON DELETE RESTRICT,
    source_system   source_system NOT NULL,
    -- The upload dataset the user declared (payments, settlement_batches,
    -- settlement_lines, ...). Finer-grained than source_system, which
    -- collapses both settlement datasets to razorpay_settlements, so it is
    -- kept alongside rather than derived from it - the Imports coverage
    -- view needs to tell those two apart.
    dataset         TEXT,
    idempotency_key TEXT,
    status          import_status NOT NULL DEFAULT 'pending',
    rows_total      INTEGER       NOT NULL DEFAULT 0,
    rows_accepted   INTEGER       NOT NULL DEFAULT 0,
    rows_rejected   INTEGER       NOT NULL DEFAULT 0,
    warnings        JSONB         NOT NULL DEFAULT '[]'::jsonb,
    error           TEXT,
    created_by      UUID REFERENCES users(id),
    started_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    CONSTRAINT ck_import_counts CHECK (
        rows_total >= 0 AND rows_accepted >= 0 AND rows_rejected >= 0
        AND rows_accepted + rows_rejected <= rows_total
    )
);
CREATE INDEX ix_imports_org_created ON imports (org_id, started_at DESC);
CREATE UNIQUE INDEX uq_import_idem ON imports (org_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Quarantine. A bad amount is NEVER coerced into a good one (PRD NFR-1).
CREATE TABLE import_rejections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    import_id     UUID    NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
    row_number    INTEGER NOT NULL,
    column_name   TEXT,
    raw_value     TEXT,
    error_code    TEXT    NOT NULL,   -- AMOUNT_PRECISION_LOSS, MISSING_FIELD, ...
    error_message TEXT    NOT NULL,
    raw_row       JSONB   NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_rejections_import ON import_rejections (import_id, row_number);
CREATE INDEX ix_rejections_code   ON import_rejections (import_id, error_code);

-- Every accepted source row, preserved exactly as received.
CREATE TABLE source_records (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID          NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    import_id      UUID          NOT NULL REFERENCES imports(id) ON DELETE RESTRICT,
    source_file_id UUID          NOT NULL REFERENCES source_files(id) ON DELETE RESTRICT,
    source_system  source_system NOT NULL,
    external_id    TEXT          NOT NULL,
    row_number     INTEGER       NOT NULL,
    raw_payload    JSONB         NOT NULL,
    row_hash       TEXT          NOT NULL,          -- sha256 over the normalised payload
    imported_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_natural UNIQUE (org_id, source_system, external_id),
    CONSTRAINT uq_source_rowhash UNIQUE (row_hash)
);
CREATE INDEX ix_source_import ON source_records (import_id);

-- =====================================================================
-- 4. CANONICAL LAYER
-- =====================================================================

CREATE TABLE canonical_transactions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             UUID          NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_record_id   UUID          NOT NULL REFERENCES source_records(id) ON DELETE RESTRICT,
    entity_type        entity_type   NOT NULL,
    source_system      source_system NOT NULL,

    -- Identifiers. Joins use *_norm; display and audit use the originals.
    external_id        TEXT          NOT NULL,
    external_id_norm   TEXT          NOT NULL,
    parent_external_id TEXT,
    reference_id       TEXT,
    customer_ref       TEXT,

    -- Money. BIGINT paise. Sign lives in `direction`, never here.
    currency           CHAR(3)       NOT NULL,
    gross_amount_minor BIGINT        NOT NULL,
    fee_amount_minor   BIGINT        NOT NULL DEFAULT 0,
    tax_amount_minor   BIGINT        NOT NULL DEFAULT 0,
    net_amount_minor   BIGINT        NOT NULL,
    direction          txn_direction NOT NULL,
    status             txn_status    NOT NULL,

    -- Time. Compare on business_date, never on raw UTC instants.
    event_at           TIMESTAMPTZ   NOT NULL,
    available_at       TIMESTAMPTZ,
    business_date      DATE          NOT NULL,
    business_timezone  TEXT          NOT NULL DEFAULT 'Asia/Kolkata',
    tz_assumed         BOOLEAN       NOT NULL DEFAULT FALSE,

    counterparty       TEXT,
    description        TEXT,                       -- untrusted input (see architecture R1)
    metadata           JSONB         NOT NULL DEFAULT '{}'::jsonb,
    data_quality_flags TEXT[]        NOT NULL DEFAULT ARRAY[]::TEXT[],
    normalized_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT uq_canon_source UNIQUE (source_record_id),

    -- THE amount identity. Holds for every row: entities without fees
    -- carry fee=0, tax=0, so net=gross. See docs/04-database-design.md 1.4.
    CONSTRAINT ck_canon_net CHECK (
        net_amount_minor = gross_amount_minor - fee_amount_minor - tax_amount_minor
    ),
    CONSTRAINT ck_canon_nonneg CHECK (
        gross_amount_minor >= 0 AND fee_amount_minor >= 0 AND tax_amount_minor >= 0
    ),
    CONSTRAINT ck_canon_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_canon_idnorm   CHECK (external_id_norm = upper(btrim(external_id))),
    -- Only settlement entities may carry fees or taxes.
    CONSTRAINT ck_canon_fee_scope CHECK (
        entity_type IN ('settlement_batch','settlement_line','adjustment')
        OR (fee_amount_minor = 0 AND tax_amount_minor = 0)
    )
);

-- Matching-engine indexes. Each exists for a named query.
CREATE INDEX ix_canon_extid   ON canonical_transactions (org_id, external_id_norm);
CREATE INDEX ix_canon_parent  ON canonical_transactions (org_id, parent_external_id)
    WHERE parent_external_id IS NOT NULL;
CREATE INDEX ix_canon_ref     ON canonical_transactions (org_id, reference_id)
    WHERE reference_id IS NOT NULL;
CREATE INDEX ix_canon_type_dt ON canonical_transactions (org_id, entity_type, business_date);
-- The candidate-window index: equality predicates, then range, then amount.
CREATE INDEX ix_canon_window  ON canonical_transactions
    (org_id, currency, direction, status, business_date, net_amount_minor);
-- R6's amount+date probe against the settlement/bank population.
CREATE INDEX ix_canon_amt_probe ON canonical_transactions (org_id, net_amount_minor, business_date)
    WHERE entity_type IN ('bank_transaction', 'settlement_batch');
CREATE INDEX ix_canon_dq ON canonical_transactions USING GIN (data_quality_flags)
    WHERE data_quality_flags <> ARRAY[]::TEXT[];

-- =====================================================================
-- 5. RUNS AND RESULTS  (versioned; never overwritten)
-- =====================================================================

CREATE TABLE dataset_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID   NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name           TEXT   NOT NULL,
    date_from      DATE   NOT NULL,
    date_to        DATE   NOT NULL,
    source_systems source_system[] NOT NULL,
    record_count   INTEGER NOT NULL DEFAULT 0,
    snapshot_hash  TEXT   NOT NULL,   -- hash of the member record id set
    created_by     UUID REFERENCES users(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_snapshot_range CHECK (date_to >= date_from)
);
CREATE INDEX ix_snapshot_org ON dataset_snapshots (org_id, created_at DESC);

CREATE TABLE reconciliation_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID       NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    snapshot_id     UUID       NOT NULL REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    policy_id       UUID       NOT NULL REFERENCES policies(id) ON DELETE RESTRICT,
    ruleset_version TEXT       NOT NULL,
    model_version   TEXT,
    status          run_status NOT NULL DEFAULT 'queued',
    current_stage   TEXT,
    progress_pct    SMALLINT   NOT NULL DEFAULT 0,
    error           TEXT,
    failed_stage    TEXT,
    triggered_by    UUID REFERENCES users(id),
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    CONSTRAINT ck_run_progress CHECK (progress_pct BETWEEN 0 AND 100)
);
CREATE INDEX ix_runs_org      ON reconciliation_runs (org_id, queued_at DESC);
CREATE INDEX ix_runs_snapshot ON reconciliation_runs (snapshot_id);

CREATE TABLE run_metrics (
    run_id                    UUID PRIMARY KEY REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
    records_processed         INTEGER NOT NULL DEFAULT 0,
    records_auto_resolved     INTEGER NOT NULL DEFAULT 0,
    records_pending_review    INTEGER NOT NULL DEFAULT 0,
    records_unresolved        INTEGER NOT NULL DEFAULT 0,
    gross_processed_minor     BIGINT  NOT NULL DEFAULT 0,
    reconciled_value_minor    BIGINT  NOT NULL DEFAULT 0,
    unresolved_value_minor    BIGINT  NOT NULL DEFAULT 0,
    groups_created            INTEGER NOT NULL DEFAULT 0,
    exceptions_created        INTEGER NOT NULL DEFAULT 0,
    invalid_rows              INTEGER NOT NULL DEFAULT 0,
    duration_ms               INTEGER,
    stage_timings             JSONB   NOT NULL DEFAULT '{}'::jsonb,
    -- Held-out evaluation, present only when ground truth exists.
    eval_partition            truth_partition,
    match_precision           NUMERIC(5,4),
    match_recall              NUMERIC(5,4),
    match_f1                  NUMERIC(5,4),
    auto_resolution_precision NUMERIC(5,4),
    false_clear_rate          NUMERIC(5,4),
    classification_accuracy   NUMERIC(5,4),
    coverage                  NUMERIC(5,4),
    computed_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reconciliation_groups (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                UUID          NOT NULL REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
    org_id                UUID          NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    group_type            group_type    NOT NULL,
    status                group_status  NOT NULL DEFAULT 'proposed',
    matched_by_rule       TEXT          NOT NULL,           -- 'R1' .. 'R7'
    tier                  rule_tier     NOT NULL,
    confidence            NUMERIC(5,4)  NOT NULL,
    confidence_components JSONB         NOT NULL DEFAULT '{}'::jsonb,
    gate_result           JSONB         NOT NULL DEFAULT '{}'::jsonb,  -- all 6 conditions, evaluated
    bridge                JSONB,        -- gross, refunds, fees, taxes, adj, net, diff, tolerance_used
    total_amount_minor    BIGINT        NOT NULL,
    currency              CHAR(3)       NOT NULL,
    explanation           TEXT,
    auto_resolved         BOOLEAN       NOT NULL DEFAULT FALSE,
    ruleset_version       TEXT          NOT NULL,
    policy_version        INTEGER       NOT NULL,
    superseded_by         UUID REFERENCES reconciliation_groups(id),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    resolved_at           TIMESTAMPTZ,
    CONSTRAINT ck_group_conf     CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_group_currency CHECK (currency ~ '^[A-Z]{3}$'),
    -- An auto-resolved group may later be superseded by a correction, so
    -- 'superseded' is permitted; it may never become 'approved'/'rejected',
    -- because a human decision on it would have to supersede it instead.
    CONSTRAINT ck_group_autoflag CHECK (
        auto_resolved = FALSE OR status IN ('auto_resolved', 'superseded')
    )
);
CREATE INDEX ix_groups_run    ON reconciliation_groups (run_id, status);
CREATE INDEX ix_groups_conf   ON reconciliation_groups (run_id, confidence DESC);
CREATE INDEX ix_groups_active ON reconciliation_groups (run_id) WHERE superseded_by IS NULL;

CREATE TABLE reconciliation_links (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id             UUID      NOT NULL REFERENCES reconciliation_groups(id) ON DELETE CASCADE,
    -- run_id is denormalised so the exclusivity index below can exist.
    run_id               UUID      NOT NULL REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
    transaction_id       UUID      NOT NULL REFERENCES canonical_transactions(id) ON DELETE RESTRICT,
    role                 link_role NOT NULL,
    matched_amount_minor BIGINT    NOT NULL,
    evidence_json        JSONB     NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_link_member UNIQUE (group_id, transaction_id),
    CONSTRAINT ck_link_amount CHECK (matched_amount_minor >= 0)
);
-- A transaction belongs to at most one group per run, unless it is
-- explicitly split-allocated. Without this, money is silently double-counted.
CREATE UNIQUE INDEX uq_link_exclusive
    ON reconciliation_links (run_id, transaction_id)
    WHERE role <> 'split_component';
CREATE INDEX ix_links_group ON reconciliation_links (group_id);
CREATE INDEX ix_links_txn   ON reconciliation_links (transaction_id);

-- Every rule fire leaves a reason, not just a result.
CREATE TABLE reconciliation_evidence (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id      UUID    NOT NULL REFERENCES reconciliation_groups(id) ON DELETE CASCADE,
    rule_code     TEXT    NOT NULL,
    evidence_type TEXT    NOT NULL,   -- 'exact_id' | 'amount_identity' | 'date_window' | ...
    statement     TEXT    NOT NULL,   -- human-readable, e.g. "settlement.payment_id == payment.id"
    computed      JSONB   NOT NULL DEFAULT '{}'::jsonb,  -- the actual values compared
    passed        BOOLEAN NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_evidence_group ON reconciliation_evidence (group_id);

-- =====================================================================
-- 6. EXCEPTIONS AND INVESTIGATION
-- =====================================================================

CREATE TABLE exception_cases (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                 UUID               NOT NULL REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
    org_id                 UUID               NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- Nullable: an unmatched payment has a case and no group.
    group_id               UUID REFERENCES reconciliation_groups(id) ON DELETE SET NULL,
    primary_transaction_id UUID REFERENCES canonical_transactions(id) ON DELETE RESTRICT,
    case_type              exception_type     NOT NULL,
    severity               exception_severity NOT NULL,
    status                 exception_status   NOT NULL DEFAULT 'open',
    amount_at_risk_minor   BIGINT             NOT NULL,
    currency               CHAR(3)            NOT NULL,
    hypothesis             TEXT,               -- engine's deterministic root-cause guess
    recommendation         TEXT,
    confidence             NUMERIC(5,4),
    assigned_to            UUID REFERENCES users(id),
    due_at                 TIMESTAMPTZ,
    opened_at              TIMESTAMPTZ        NOT NULL DEFAULT now(),
    resolved_at            TIMESTAMPTZ,
    resolved_by            UUID REFERENCES users(id),
    resolution             case_resolution,
    resolution_reason_code TEXT,
    resolution_note        TEXT,
    CONSTRAINT ck_case_amount CHECK (amount_at_risk_minor >= 0),
    CONSTRAINT ck_case_conf   CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    -- PRD story D1: an override must state its reason.
    CONSTRAINT ck_case_override_reason CHECK (
        resolution IS DISTINCT FROM 'overridden' OR resolution_reason_code IS NOT NULL
    ),
    CONSTRAINT ck_case_resolved CHECK (
        (status IN ('resolved','dismissed')) = (resolved_at IS NOT NULL)
    )
);
-- The hottest query in the product: the queue, worst money first.
CREATE INDEX ix_cases_queue ON exception_cases (run_id, status, amount_at_risk_minor DESC);
CREATE INDEX ix_cases_assignee ON exception_cases (assigned_to, status)
    WHERE assigned_to IS NOT NULL;
CREATE INDEX ix_cases_type ON exception_cases (run_id, case_type, severity);
CREATE INDEX ix_cases_aging ON exception_cases (org_id, opened_at)
    WHERE status NOT IN ('resolved','dismissed');

-- A case may involve records that are in no group at all.
CREATE TABLE exception_case_transactions (
    case_id        UUID NOT NULL REFERENCES exception_cases(id) ON DELETE CASCADE,
    transaction_id UUID NOT NULL REFERENCES canonical_transactions(id) ON DELETE RESTRICT,
    role           TEXT NOT NULL,     -- 'subject' | 'expected_counterpart' | 'context'
    PRIMARY KEY (case_id, transaction_id)
);
CREATE INDEX ix_case_txn ON exception_case_transactions (transaction_id);

-- Every candidate considered, with why it was rejected. This is what makes
-- abstention legible rather than a shrug.
CREATE TABLE match_candidates (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id                UUID         NOT NULL REFERENCES exception_cases(id) ON DELETE CASCADE,
    transaction_id         UUID         NOT NULL REFERENCES canonical_transactions(id) ON DELETE RESTRICT,
    candidate_txn_id       UUID         NOT NULL REFERENCES canonical_transactions(id) ON DELETE RESTRICT,
    score                  NUMERIC(5,4) NOT NULL,
    score_components       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    rank                   SMALLINT     NOT NULL,
    accepted               BOOLEAN      NOT NULL DEFAULT FALSE,
    rejection_reason       TEXT,
    margin_to_runner_up    NUMERIC(5,4),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_cand_score CHECK (score BETWEEN 0 AND 1),
    CONSTRAINT uq_cand UNIQUE (case_id, transaction_id, candidate_txn_id)
);
CREATE INDEX ix_cand_case ON match_candidates (case_id, rank);

-- The model's output, quarantined. NO financial columns, by design.
CREATE TABLE ai_investigations (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id                UUID                NOT NULL REFERENCES exception_cases(id) ON DELETE CASCADE,
    model_version          TEXT                NOT NULL,
    prompt_version         TEXT                NOT NULL,
    packet_hash            TEXT                NOT NULL,
    validation_status      ai_validation_status NOT NULL,
    validation_errors      JSONB               NOT NULL DEFAULT '[]'::jsonb,
    classification         exception_type,     -- validated against the enum
    hypotheses             JSONB               NOT NULL DEFAULT '[]'::jsonb,
    recommended_action     TEXT,
    requires_human_approval BOOLEAN,
    confidence             NUMERIC(5,4),       -- ADVISORY ONLY. Never gates a resolution.
    uncertainties          JSONB               NOT NULL DEFAULT '[]'::jsonb,
    cited_evidence_ids     TEXT[]              NOT NULL DEFAULT ARRAY[]::TEXT[],
    latency_ms             INTEGER,
    input_tokens           INTEGER,
    output_tokens          INTEGER,
    requested_by           UUID REFERENCES users(id),
    created_at             TIMESTAMPTZ         NOT NULL DEFAULT now(),
    CONSTRAINT ck_ai_conf CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);
CREATE INDEX ix_ai_case ON ai_investigations (case_id, created_at DESC);
-- Grounding violations are a metric worth watching, so they are kept, not dropped.
CREATE INDEX ix_ai_violations ON ai_investigations (validation_status)
    WHERE validation_status <> 'valid';

CREATE TABLE case_comments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id    UUID NOT NULL REFERENCES exception_cases(id) ON DELETE CASCADE,
    author_id  UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_comment_body CHECK (length(btrim(body)) > 0)
);
CREATE INDEX ix_comments_case ON case_comments (case_id, created_at);

-- =====================================================================
-- 7. AUDIT  (append-only)
-- =====================================================================

CREATE TABLE decision_audit_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID            NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    entity_type     TEXT            NOT NULL,   -- polymorphic: 'exception_case', 'group', ...
    entity_id       UUID            NOT NULL,
    action          decision_action NOT NULL,
    actor_type      actor_type      NOT NULL,
    actor_id        UUID REFERENCES users(id),
    actor_role      user_role,
    reason_code     TEXT,
    ruleset_version TEXT,
    model_version   TEXT,
    policy_version  INTEGER,
    payload_json    JSONB           NOT NULL DEFAULT '{}'::jsonb,  -- before/after
    prev_hash       TEXT,
    event_hash      TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    CONSTRAINT ck_audit_actor CHECK (
        (actor_type = 'user') = (actor_id IS NOT NULL)
    )
);
CREATE INDEX ix_audit_entity ON decision_audit_events (entity_type, entity_id, created_at DESC);
CREATE INDEX ix_audit_actor  ON decision_audit_events (actor_id, created_at DESC);
CREATE INDEX ix_audit_org    ON decision_audit_events (org_id, created_at DESC);

-- =====================================================================
-- 8. EVALUATION AND IDEMPOTENCY
-- =====================================================================

-- Written by the synthetic generator only. The matching engine has no
-- import path to this table.
CREATE TABLE ground_truth_links (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id      UUID            NOT NULL REFERENCES dataset_snapshots(id) ON DELETE CASCADE,
    truth_id         TEXT            NOT NULL,
    relation_type    TEXT            NOT NULL,   -- 'payment_settlement_bank', 'invoice_payment', ...
    external_ids     TEXT[]          NOT NULL,
    expected_group   group_type,
    injected_anomaly TEXT,                       -- NULL for clean cases
    partition        truth_partition NOT NULL,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT now(),
    CONSTRAINT uq_truth UNIQUE (snapshot_id, truth_id)
);
CREATE INDEX ix_truth_partition ON ground_truth_links (snapshot_id, partition);
CREATE INDEX ix_truth_anomaly   ON ground_truth_links (snapshot_id, injected_anomaly)
    WHERE injected_anomaly IS NOT NULL;

CREATE TABLE idempotency_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    endpoint        TEXT        NOT NULL,
    key             TEXT        NOT NULL,
    request_hash    TEXT        NOT NULL,
    response_status SMALLINT,
    response_body   JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '24 hours'),
    CONSTRAINT uq_idem UNIQUE (org_id, endpoint, key)
);
CREATE INDEX ix_idem_expiry ON idempotency_keys (expires_at);

-- =====================================================================
-- 9. TRIGGERS  (guarantees that must not depend on application code)
-- =====================================================================

-- 9.1 The audit log is append-only. Not by convention — by refusal.
CREATE OR REPLACE FUNCTION trg_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'decision_audit_events is append-only (attempted %)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_no_update
    BEFORE UPDATE ON decision_audit_events
    FOR EACH ROW EXECUTE FUNCTION trg_audit_append_only();

CREATE TRIGGER audit_no_delete
    BEFORE DELETE ON decision_audit_events
    FOR EACH ROW EXECUTE FUNCTION trg_audit_append_only();

-- 9.2 Split allocation must conserve money exactly.
--     Deferred so a multi-row allocation can be inserted within one transaction.
CREATE OR REPLACE FUNCTION trg_check_split_allocation() RETURNS trigger AS $$
DECLARE
    v_txn        UUID;
    v_run        UUID;
    v_allocated  BIGINT;
    v_net        BIGINT;
BEGIN
    -- NEW is unassigned on DELETE and OLD is unassigned on INSERT; touching
    -- the wrong one raises "record is not assigned yet", so branch on TG_OP.
    IF TG_OP = 'DELETE' THEN
        v_txn := OLD.transaction_id;
        v_run := OLD.run_id;
    ELSE
        v_txn := NEW.transaction_id;
        v_run := NEW.run_id;
    END IF;

    SELECT COALESCE(SUM(matched_amount_minor), 0)
      INTO v_allocated
      FROM reconciliation_links
     WHERE transaction_id = v_txn
       AND run_id = v_run
       AND role = 'split_component';

    IF v_allocated = 0 THEN
        RETURN NULL;   -- no split allocation for this transaction in this run
    END IF;

    SELECT net_amount_minor INTO v_net
      FROM canonical_transactions WHERE id = v_txn;

    IF v_allocated <> v_net THEN
        RAISE EXCEPTION
            'split allocation for transaction % in run % sums to % but net is %',
            v_txn, v_run, v_allocated, v_net
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER check_split_allocation
    AFTER INSERT OR UPDATE OR DELETE ON reconciliation_links
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_check_split_allocation();

-- 9.3 A group cannot be resolved without evidence (PRD NFR-3).
CREATE OR REPLACE FUNCTION trg_require_evidence() RETURNS trigger AS $$
DECLARE
    v_count INTEGER;
BEGIN
    IF NEW.status IN ('auto_resolved', 'approved') THEN
        SELECT count(*) INTO v_count
          FROM reconciliation_evidence
         WHERE group_id = NEW.id AND passed;

        IF v_count = 0 THEN
            RAISE EXCEPTION
                'group % cannot reach status % with no passing evidence', NEW.id, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER require_evidence
    AFTER INSERT OR UPDATE ON reconciliation_groups
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_require_evidence();

-- 9.4 updated_at maintenance
CREATE OR REPLACE FUNCTION trg_touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_touch
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();

-- =====================================================================
-- 10. VIEWS
-- =====================================================================

-- Removes the N+1 on the queue page (architecture P3).
CREATE VIEW v_exception_queue AS
SELECT
    c.id,
    c.run_id,
    c.org_id,
    c.case_type,
    c.severity,
    c.status,
    c.amount_at_risk_minor,
    c.currency,
    c.confidence,
    c.opened_at,
    (CURRENT_DATE - c.opened_at::date)          AS age_days,
    c.assigned_to,
    u.full_name                                  AS assignee_name,
    t.external_id                                AS primary_external_id,
    t.entity_type                                AS primary_entity_type,
    t.source_system                              AS primary_source_system,
    t.business_date                              AS primary_business_date,
    g.matched_by_rule,
    g.group_type,
    EXISTS (SELECT 1 FROM ai_investigations a
             WHERE a.case_id = c.id AND a.validation_status = 'valid') AS has_ai_investigation
FROM exception_cases c
LEFT JOIN users u                   ON u.id = c.assigned_to
LEFT JOIN canonical_transactions t   ON t.id = c.primary_transaction_id
LEFT JOIN reconciliation_groups g    ON g.id = c.group_id;

-- Drives the overview cards and the export header.
CREATE VIEW v_reconciliation_summary AS
SELECT
    r.id                                                         AS run_id,
    r.org_id,
    r.status                                                     AS run_status,
    r.completed_at,
    m.records_processed,
    m.records_auto_resolved,
    m.records_pending_review,
    m.records_unresolved,
    m.gross_processed_minor,
    m.reconciled_value_minor,
    m.unresolved_value_minor,
    CASE WHEN m.records_processed > 0
         THEN ROUND(m.records_auto_resolved::numeric / m.records_processed, 4)
         ELSE NULL END                                           AS auto_resolution_rate,
    CASE WHEN m.gross_processed_minor > 0
         THEN ROUND(m.reconciled_value_minor::numeric / m.gross_processed_minor, 4)
         ELSE NULL END                                           AS reconciled_value_rate,
    m.match_precision,
    m.match_recall,
    m.auto_resolution_precision,
    m.false_clear_rate,
    m.coverage
FROM reconciliation_runs r
LEFT JOIN run_metrics m ON m.run_id = r.id;

-- =====================================================================
-- 11. GRANTS
-- The application role can never rewrite history, even if compromised.
-- Run against the role the API actually connects as.
-- =====================================================================

-- CREATE ROLE ledgergraph_app LOGIN PASSWORD :'app_password';
-- GRANT USAGE ON SCHEMA public TO ledgergraph_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ledgergraph_app;
-- REVOKE UPDATE, DELETE ON decision_audit_events FROM ledgergraph_app;
-- REVOKE UPDATE, DELETE ON source_records        FROM ledgergraph_app;
-- REVOKE UPDATE, DELETE ON source_files          FROM ledgergraph_app;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA public  TO ledgergraph_app;

COMMIT;
