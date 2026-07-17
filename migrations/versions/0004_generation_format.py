"""Add selectable canvas formats for text-to-image jobs."""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_generation_format"
down_revision: str | None = "0003_batches_library"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "generation_jobs",
        sa.Column(
            "generation_format",
            sa.Enum(
                "portrait",
                "square",
                "landscape",
                name="generationformat",
                native_enum=False,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("generation_jobs", "generation_format")
