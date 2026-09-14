"""Submissions are handed in explicitly

Revision ID: c2d5f8a31b47
Revises: b1c4e7a92f10
"""

from alembic import op
import sqlalchemy as sa

revision = "c2d5f8a31b47"
down_revision = "b1c4e7a92f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("submitted_at", sa.DateTime(), nullable=True))
    # Everything that already exists was uploaded under the old rule,
    # where arriving *was* handing in. Leaving these null would make
    # every past submission look unfinished and drop it out of marking.
    op.execute("UPDATE submissions SET submitted_at = created_at")


def downgrade() -> None:
    op.drop_column("submissions", "submitted_at")
