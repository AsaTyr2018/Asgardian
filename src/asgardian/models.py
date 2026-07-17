import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class GenerationMode(StrEnum):
    text_to_image = "text_to_image"
    image_edit = "image_edit"


class GenerationFormat(StrEnum):
    portrait = "portrait"
    square = "square"
    landscape = "landscape"


class Wall(Base):
    __tablename__ = "walls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    capability_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    jobs: Mapped[list["GenerationJob"]] = relationship(back_populates="wall", cascade="all, delete-orphan")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        Index("ix_generation_jobs_claim", "status", "created_at"),
        Index("ix_generation_jobs_wall", "wall_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    wall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("walls.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[GenerationMode] = mapped_column(Enum(GenerationMode, native_enum=False), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.queued, nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation_format: Mapped[GenerationFormat | None] = mapped_column(
        Enum(GenerationFormat, native_enum=False)
    )
    source_object_key: Mapped[str | None] = mapped_column(Text)
    result_object_key: Mapped[str | None] = mapped_column(Text)
    thumbnail_object_key: Mapped[str | None] = mapped_column(Text)
    result_width: Mapped[int | None] = mapped_column(Integer)
    result_height: Mapped[int | None] = mapped_column(Integer)
    engine_id: Mapped[str | None] = mapped_column(String(64))
    comfy_prompt_id: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    wall: Mapped[Wall] = relationship(back_populates="jobs")


class SavedAsset(Base):
    __tablename__ = "saved_assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_generation_id: Mapped[uuid.UUID] = mapped_column(unique=True, nullable=False)
    mode: Mapped[GenerationMode] = mapped_column(Enum(GenerationMode, native_enum=False), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    thumbnail_object_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_format: Mapped[GenerationFormat | None] = mapped_column(
        Enum(GenerationFormat, native_enum=False)
    )
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    videos: Mapped[list["VideoJob"]] = relationship(
        back_populates="saved_asset", cascade="all, delete-orphan"
    )


class VideoJob(Base):
    __tablename__ = "video_jobs"
    __table_args__ = (Index("ix_video_jobs_claim", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    saved_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.queued, nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fps: Mapped[int] = mapped_column(default=60, nullable=False)
    frame_count: Mapped[int] = mapped_column(default=721, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(default=12, nullable=False)
    result_object_key: Mapped[str | None] = mapped_column(Text)
    engine_id: Mapped[str | None] = mapped_column(String(64))
    comfy_prompt_id: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    saved_asset: Mapped[SavedAsset] = relationship(back_populates="videos")
