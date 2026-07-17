from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class EngineRoutingMode(StrEnum):
    solo = "solo"
    split = "split"


def _is_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASGARDIAN_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://asgardian:asgardian@localhost:5432/asgardian"
    redis_url: str = "redis://localhost:6379/0"
    engine_routing_mode: EngineRoutingMode = EngineRoutingMode.solo
    comfy_url: str = "http://comfyui.example.local:8188"
    comfy_image_url: str | None = None
    comfy_video_url: str | None = None
    s3_endpoint: str = "https://s3.example.local"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "artefacts"
    s3_tls_verify: bool = False
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])
    workflow_dir: Path = Path("workflows")
    wall_ttl_seconds: int = 86_400
    cleanup_batch_size: int = 100
    poll_interval_seconds: float = 1.0
    event_stream_max_length: int = 10_000

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def split_csv(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("comfy_url", "comfy_image_url", "comfy_video_url", mode="before")
    @classmethod
    def normalize_engine_url(cls, value):
        if value is None:
            return None
        normalized = str(value).strip().rstrip("/")
        return normalized or None

    @model_validator(mode="after")
    def validate_engine_routing(self):
        if not self.comfy_url or not _is_http_url(self.comfy_url):
            raise ValueError("comfy_url must be an absolute HTTP(S) URL")
        if self.engine_routing_mode == EngineRoutingMode.solo:
            return self
        if not self.comfy_image_url or not self.comfy_video_url:
            raise ValueError("split routing requires comfy_image_url and comfy_video_url")
        if not _is_http_url(self.comfy_image_url) or not _is_http_url(self.comfy_video_url):
            raise ValueError("split engine URLs must be absolute HTTP(S) URLs")
        if self.comfy_image_url == self.comfy_video_url:
            raise ValueError("split routing requires two distinct ComfyUI URLs")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
