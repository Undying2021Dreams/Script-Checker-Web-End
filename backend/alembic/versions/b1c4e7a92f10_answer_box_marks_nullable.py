"""Answer box marks may be unset

Revision ID: b1c4e7a92f10
Revises: fa6ada92d057
"""

from alembic import op
import sqlalchemy as sa

revision = "b1c4e7a92f10"
down_revision = "fa6ada92d057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "Not decided yet" had no representation, so it was indistinguishable
    # from a part worth one mark — which is what every box defaulted to,
    # and why marking schemes worth ten were being marked out of one.
    op.alter_column("answer_boxes", "points", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Anything still unset has to take a value again before the column can
    # refuse nulls.
    op.execute("UPDATE answer_boxes SET points = 1 WHERE points IS NULL")
    op.alter_column("answer_boxes", "points", existing_type=sa.Integer(), nullable=False)
