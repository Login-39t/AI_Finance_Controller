"""Add 'deactivated' to decision_action.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05

Admin user management can now deactivate an account (a soft delete: the
row stays so the audit trail it authored survives, but the user can no
longer sign in). That action is recorded in the audit table, whose action
column is typed `decision_action`, so the enum needs the new value or the
first `deactivated` INSERT fails with `invalid input value for enum`.

As with 0002, `db/schema.sql` now carries this value for a fresh database
and `ADD VALUE IF NOT EXISTS` makes this delta a no-op where the value
already exists - safe on both a fresh and an already-migrated database.
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE decision_action ADD VALUE IF NOT EXISTS 'deactivated'")


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum without recreating the
    # type and rewriting every column that uses it, so this is a no-op -
    # the same stance revisions 0002 took.
    pass
