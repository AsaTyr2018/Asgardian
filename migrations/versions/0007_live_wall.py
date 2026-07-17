"""live wall events and thumbnails

Revision ID: 0007_live_wall
Revises: 0006_engine_routing
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_live_wall"
down_revision = "0006_engine_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("thumbnail_object_key", sa.Text(), nullable=True))
    op.add_column("generation_jobs", sa.Column("result_width", sa.Integer(), nullable=True))
    op.add_column("generation_jobs", sa.Column("result_height", sa.Integer(), nullable=True))
    op.add_column("saved_assets", sa.Column("thumbnail_object_key", sa.Text(), nullable=True))
    generation_format = sa.Enum(
        "portrait", "square", "landscape", name="generationformat", native_enum=False
    )
    op.add_column("saved_assets", sa.Column("generation_format", generation_format, nullable=True))
    op.add_column("saved_assets", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("saved_assets", sa.Column("height", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("saved_assets", "height")
    op.drop_column("saved_assets", "width")
    op.drop_column("saved_assets", "generation_format")
    op.drop_column("saved_assets", "thumbnail_object_key")
    op.drop_column("generation_jobs", "result_height")
    op.drop_column("generation_jobs", "result_width")
    op.drop_column("generation_jobs", "thumbnail_object_key")
