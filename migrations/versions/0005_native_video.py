"""Add native LTX image-to-video jobs."""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_native_video"
down_revision: str | None = "0004_generation_format"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "video_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("saved_asset_id", sa.Uuid(), nullable=False),
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
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("fps", sa.Integer(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("result_object_key", sa.Text(), nullable=True),
        sa.Column("comfy_prompt_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["saved_asset_id"], ["saved_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_jobs_claim", "video_jobs", ["status", "created_at"])
    op.create_index(op.f("ix_video_jobs_saved_asset_id"), "video_jobs", ["saved_asset_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_video_jobs_saved_asset_id"), table_name="video_jobs")
    op.drop_index("ix_video_jobs_claim", table_name="video_jobs")
    op.drop_table("video_jobs")
