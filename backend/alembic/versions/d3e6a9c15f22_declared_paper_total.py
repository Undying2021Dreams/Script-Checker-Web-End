"""A paper may state what it is out of

Revision ID: d3e6a9c15f22
Revises: c2d5f8a31b47
"""

from alembic import op
import sqlalchemy as sa

revision = "d3e6a9c15f22"
down_revision = "c2d5f8a31b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable and unset for everything that exists: it is a check a
    # teacher opts into, not a value every paper must now carry.
    op.add_column("questions", sa.Column("total_marks_declared", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "total_marks_declared")
