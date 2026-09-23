"""A teacher's comment keeps its formatting

Revision ID: e7f1b2c48d93
Revises: d3e6a9c15f22
"""

from alembic import op
import sqlalchemy as sa

revision = "e7f1b2c48d93"
down_revision = "d3e6a9c15f22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive and empty for everything that exists. The flattened text
    # in `override_feedback` stays the source of truth for anything that
    # only wants words, so a comment written before this still reads
    # correctly everywhere — there is nothing to backfill.
    op.add_column(
        "answer_grades",
        sa.Column("override_feedback_doc", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("answer_grades", "override_feedback_doc")
