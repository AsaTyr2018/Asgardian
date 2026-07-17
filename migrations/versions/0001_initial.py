"""Initial wall and generation job schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "walls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capability_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("wall_id", sa.Uuid(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum("text_to_image", "image_edit", name="generationmode", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="jobstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("source_object_key", sa.Text(), nullable=True),
        sa.Column("result_object_key", sa.Text(), nullable=True),
        sa.Column("comfy_prompt_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["wall_id"], ["walls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generation_jobs_claim", "generation_jobs", ["status", "created_at"])
    op.create_index("ix_generation_jobs_wall", "generation_jobs", ["wall_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_wall", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_claim", table_name="generation_jobs")
    op.drop_table("generation_jobs")
    op.drop_table("walls")
