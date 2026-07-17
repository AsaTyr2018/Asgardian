"""Add generation batches and the persistent personal library."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_batches_library"
down_revision: str | None = "0002_seed_bigint"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("batch_id", sa.Uuid(), nullable=True))
    op.create_index("ix_generation_jobs_batch_id", "generation_jobs", ["batch_id"])
    op.create_table(
        "saved_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_generation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum("text_to_image", "image_edit", name="generationmode", native_enum=False),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint("source_generation_id"),
    )


def downgrade() -> None:
    op.drop_table("saved_assets")
    op.drop_index("ix_generation_jobs_batch_id", table_name="generation_jobs")
    op.drop_column("generation_jobs", "batch_id")
