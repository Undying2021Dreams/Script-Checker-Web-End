"""Join requests, notifications, and editable profiles

Revision ID: f8a2c31e76b4
Revises: e7f1b2c48d93
"""

from alembic import op
import sqlalchemy as sa

revision = "f8a2c31e76b4"
down_revision = "e7f1b2c48d93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All additive. Joining by code is untouched, so every existing
    # enrollment stays exactly as it is and there is nothing to backfill.
    op.add_column("users", sa.Column("institution", sa.String(), nullable=True))
    op.add_column("users", sa.Column("avatar", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("avatar_content_type", sa.String(), nullable=True))

    op.create_table(
        "enrollment_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "declined", name="enrollment_request_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("course_id", "student_id", name="uq_request_course_student"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=True),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("enrollment_requests")
    sa.Enum(name="enrollment_request_status").drop(op.get_bind(), checkfirst=True)
    op.drop_column("users", "avatar_content_type")
    op.drop_column("users", "avatar")
    op.drop_column("users", "institution")
