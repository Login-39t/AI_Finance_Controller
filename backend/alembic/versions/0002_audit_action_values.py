"""Add 'registered' and 'refresh_reuse_detected' to decision_action.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

The auth router records two audit actions the original `decision_action`
enum did not include: `registered` (self-registration) and
`refresh_reuse_detected` (a consumed refresh token presented again). The
audit column is typed as that enum, so the first real INSERT for either
action failed on a production Postgres with `invalid input value for enum
decision_action`.

Revision 0001 applied `db/schema.sql` verbatim, and that file now also
carries these two values for a fresh database. This delta brings an
already-migrated database in line. `ADD VALUE IF NOT EXISTS` makes it a
no-op where 0001 already created the values, so it is safe on both a fresh
and an existing database.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE is transaction-safe on PostgreSQL 12+ as long as the new
    # value is not used in the same transaction; this migration only adds.
    op.execute("ALTER TYPE decision_action ADD VALUE IF NOT EXISTS 'registered'")
    op.execute(
        "ALTER TYPE decision_action ADD VALUE IF NOT EXISTS 'refresh_reuse_detected'"
    )


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum without recreating the
    # type and rewriting every column that uses it. There is no safe
    # partial teardown, so this is intentionally a no-op.
    pass
