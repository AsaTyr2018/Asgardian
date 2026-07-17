import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import GenerationFormat, GenerationMode, JobStatus


class WallCreated(BaseModel):
    id: uuid.UUID
    capability: str
    expires_at: datetime


class WallHeartbeat(BaseModel):
    expires_at: datetime


class GenerationCreated(BaseModel):
    id: uuid.UUID
    status: JobStatus
    mode: GenerationMode
    reserved: int = 1


class GenerationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID | None = None
    wall_id: uuid.UUID
    status: JobStatus
    mode: GenerationMode
    engine_id: str | None = None
    generation_format: GenerationFormat | None = None
    prompt: str
    seed: int
    created_at: datetime
    completed_at: datetime | None = None
    result_url: str | None = None
    thumbnail_url: str | None = None
    download_url: str | None = None
    width: int | None = None
    height: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class GenerationList(BaseModel):
    items: list[GenerationView]


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])


class SavedAssetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_generation_id: uuid.UUID
    mode: GenerationMode
    prompt: str
    seed: int
    generation_format: GenerationFormat | None = None
    width: int | None = None
    height: int | None = None
    created_at: datetime
    asset_url: str = ""
    thumbnail_url: str = ""
    download_url: str = ""


class SavedAssetList(BaseModel):
    items: list[SavedAssetView]


class VideoCreated(BaseModel):
    id: uuid.UUID
    status: JobStatus


class VideoView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    saved_asset_id: uuid.UUID
    status: JobStatus
    engine_id: str | None = None
    prompt: str
    seed: int
    fps: int
    frame_count: int
    duration_seconds: int
    created_at: datetime
    completed_at: datetime | None = None
    video_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class VideoList(BaseModel):
    items: list[VideoView]


class LiveSnapshot(BaseModel):
    generations: list[GenerationView]
    saved_assets: list[SavedAssetView]
    videos: list[VideoView]
