"""Widen generation seeds to signed 64-bit integers."""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_seed_bigint"
down_revision: str | None = "0001_initial"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "generation_jobs",
        "seed",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "generation_jobs",
        "seed",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
