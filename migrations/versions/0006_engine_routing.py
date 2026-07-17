"""Pin image and video jobs to explicit inference engines."""

import sqlalchemy as sa
from alembic import op

revision: str = "0006_engine_routing"
down_revision: str | None = "0005_native_video"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("engine_id", sa.String(length=64), nullable=True))
    op.add_column("video_jobs", sa.Column("engine_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("video_jobs", "engine_id")
    op.drop_column("generation_jobs", "engine_id")
