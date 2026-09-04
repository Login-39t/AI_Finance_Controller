"""Add imports.dataset to preserve the declared upload dataset.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05

The `imports` table only stored `source_system`, whose enum collapses
`settlement_batches` and `settlement_lines` into a single
`razorpay_settlements`. Reconstructing an import from the row therefore
lost the finer dataset the user declared, and the Imports "source
coverage" view - which checks each of the six datasets - could only ever
light up the two whose name happens to equal their source_system
(`bank_statement`, `invoices`).

Keeping the declared dataset alongside `source_system` fixes that. The
column is nullable; rows written before this migration (there are none on
a reset demo, but be safe) read back with the source_system as a fallback.
`db/schema.sql` carries the column for a fresh database.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("imports", sa.Column("dataset", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("imports", "dataset")
