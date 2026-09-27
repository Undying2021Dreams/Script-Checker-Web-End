"""On-device grading runs

Revision ID: a9c4d2e81f37
Revises: f8a2c31e76b4
"""

from alembic import op
import sqlalchemy as sa

revision = "a9c4d2e81f37"
down_revision = "f8a2c31e76b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All additive and nullable: every existing submission simply has no
    # phone run, which is what null says. Nothing to backfill.
    op.add_column("submissions", sa.Column("on_device_run_token", sa.String(), nullable=True))
    op.add_column("submissions", sa.Column("on_device_started_at", sa.DateTime(), nullable=True))
    op.add_column("submissions", sa.Column("on_device_posted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("submissions", "on_device_posted_at")
    op.drop_column("submissions", "on_device_started_at")
    op.drop_column("submissions", "on_device_run_token")
