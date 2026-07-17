import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asgardian.comfy import ComfyClient, WorkflowRegistry
from asgardian.config import EngineRoutingMode, Settings
from asgardian.engines import EngineCapability, EngineRegistry
from asgardian.ltx import build_native_video_workflow, video_dimensions
from asgardian.models import (
    Base,
    GenerationFormat,
    GenerationJob,
    GenerationMode,
    JobStatus,
    SavedAsset,
    VideoJob,
    Wall,
)
from asgardian.queue import claim_next_job, claim_next_video
from asgardian.worker import FORMAT_DIMENSIONS, latent_dimension, restore_source_dimensions, source_dimensions


def test_workflow_registry_replaces_only_declared_values():
    registry = WorkflowRegistry(__import__("pathlib").Path("workflows"))
    workflow = registry.render(
        "qwen-image-edit.api.json",
        prompt="Move the subject",
        negative_prompt="blur",
        seed=123,
        source_image="input/test.png",
        width=640,
        height=960,
        output_prefix="Asgardian/test",
    )
    serialized = json.dumps(workflow)
    assert "${" not in serialized
    assert "Move the subject" in serialized
    assert "input/test.png" in serialized
    assert workflow["3"]["inputs"]["width"] == 640
    assert workflow["3"]["inputs"]["height"] == 960
    assert any(node["class_type"] == "TextEncodeQwenImageEditPlus" for node in workflow.values())


def test_text_generation_formats_render_expected_dimensions():
    registry = WorkflowRegistry(__import__("pathlib").Path("workflows"))
    for generation_format, (width, height) in FORMAT_DIMENSIONS.items():
        workflow = registry.render(
            "qwen-text-to-image.api.json",
            prompt="A gate",
            negative_prompt="",
            seed=7,
            width=width,
            height=height,
            output_prefix=f"Asgardian/{generation_format}",
        )
        assert workflow["5"]["inputs"]["width"] == width
        assert workflow["5"]["inputs"]["height"] == height

    assert FORMAT_DIMENSIONS[GenerationFormat.portrait] == (896, 1152)
    assert FORMAT_DIMENSIONS[GenerationFormat.square] == (1024, 1024)
    assert FORMAT_DIMENSIONS[GenerationFormat.landscape] == (1152, 896)


def test_image_edit_restores_exact_source_dimensions():
    import io

    from PIL import Image

    source = io.BytesIO()
    Image.new("RGB", (641, 959), "navy").save(source, format="JPEG")
    generated = io.BytesIO()
    Image.new("RGB", (640, 960), "gold").save(generated, format="PNG")

    expected = source_dimensions(source.getvalue())
    result, content_type = restore_source_dimensions(generated.getvalue(), "image/png", expected)

    assert expected == (641, 959)
    assert (latent_dimension(expected[0]), latent_dimension(expected[1])) == (640, 960)
    assert source_dimensions(result) == expected
    assert content_type == "image/png"


def test_native_video_workflow_is_12_seconds_at_60fps_without_interpolation():
    workflow = build_native_video_workflow(
        source_image="input.png",
        prompt="The subject dances",
        seed=42,
        width=512,
        height=512,
        output_prefix="Asgardian/test",
    )

    assert workflow["8"]["inputs"]["frame_rate"] == 60.0
    assert workflow["10"]["inputs"]["length"] == 721
    assert workflow["11"]["inputs"]["frames_number"] == 721
    assert workflow["4"]["inputs"]["strength_model"] == 1.0
    assert "buddr" in workflow["6"]["inputs"]["text"]
    assert not any("interpol" in node["class_type"].lower() for node in workflow.values())
    assert video_dimensions(1024, 1024) == (512, 512)
    assert video_dimensions(1600, 900) == (640, 384)
    assert video_dimensions(900, 1600) == (384, 640)
    assert video_dimensions(1152, 896) == (576, 448)


def test_video_dimensions_stay_inside_validated_pixel_budget():
    for source_width, source_height in ((4096, 256), (256, 4096), (1920, 1080), (800, 600)):
        width, height = video_dimensions(source_width, source_height)
        assert width % 64 == 0
        assert height % 64 == 0
        assert width * height <= 512 * 512


def test_video_dimensions_reject_invalid_sources():
    with pytest.raises(ValueError, match="must be positive"):
        video_dimensions(0, 1024)


@pytest.mark.asyncio
async def test_claim_is_single_and_transitions_to_running():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        wall = Wall(capability_hash="x" * 64, expires_at=datetime.now(UTC) + timedelta(hours=1))
        session.add(wall)
        await session.flush()
        job = GenerationJob(
            id=uuid.uuid4(),
            wall_id=wall.id,
            mode=GenerationMode.text_to_image,
            prompt="test",
            seed=1,
        )
        session.add(job)
        await session.commit()
    async with sessions() as session:
        claimed = await claim_next_job(session, "image-engine")
        assert claimed is not None
        assert claimed.status == JobStatus.running
        assert claimed.engine_id == "image-engine"
    async with sessions() as session:
        assert await claim_next_job(session) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_video_claim_pins_the_configured_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        asset = SavedAsset(
            source_generation_id=uuid.uuid4(),
            mode=GenerationMode.text_to_image,
            prompt="source",
            seed=1,
            object_key="persistent/test/source.png",
            content_type="image/png",
        )
        session.add(asset)
        await session.flush()
        session.add(VideoJob(saved_asset_id=asset.id, prompt="animate", seed=2))
        await session.commit()
    async with sessions() as session:
        claimed = await claim_next_video(session, "video-engine")
        assert claimed is not None
        assert claimed.status == JobStatus.running
        assert claimed.engine_id == "video-engine"
    await engine.dispose()


def test_csv_settings_are_accepted_from_environment(monkeypatch):
    monkeypatch.setenv("ASGARDIAN_ALLOWED_HOSTS", "asgardian.example.local,localhost")
    monkeypatch.setenv("ASGARDIAN_ALLOWED_ORIGINS", "http://asgardian.example.local")

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts == ["asgardian.example.local", "localhost"]
    assert settings.allowed_origins == ["http://asgardian.example.local"]


def test_solo_engine_registry_routes_both_capabilities_to_primary_engine():
    settings = Settings(_env_file=None, comfy_url="http://comfyui.example.local:8188")
    registry = EngineRegistry(settings)

    assert registry.mode == EngineRoutingMode.solo
    assert registry.for_capability(EngineCapability.image).id == "primary"
    assert registry.for_capability(EngineCapability.video).id == "primary"
    assert registry.for_capability(EngineCapability.image).url == "http://comfyui.example.local:8188"


def test_split_engine_registry_routes_to_distinct_explicit_targets():
    settings = Settings(
        _env_file=None,
        engine_routing_mode="split",
        comfy_image_url="https://image.example.test/",
        comfy_video_url="https://video.example.test/",
    )
    registry = EngineRegistry(settings)

    assert registry.mode == EngineRoutingMode.split
    assert registry.for_capability(EngineCapability.image).id == "image-engine"
    assert registry.for_capability(EngineCapability.image).url == "https://image.example.test"
    assert registry.for_capability(EngineCapability.video).id == "video-engine"
    assert registry.for_capability(EngineCapability.video).url == "https://video.example.test"


@pytest.mark.parametrize(
    ("image_url", "video_url", "message"),
    (
        (None, "https://video.example.test", "requires comfy_image_url"),
        ("https://same.example.test", "https://same.example.test", "two distinct"),
        ("not-a-url", "https://video.example.test", "absolute HTTP"),
    ),
)
def test_split_settings_fail_closed(image_url, video_url, message):
    with pytest.raises(ValueError, match=message):
        Settings(
            _env_file=None,
            engine_routing_mode="split",
            comfy_image_url=image_url,
            comfy_video_url=video_url,
        )


def test_registry_rejects_a_job_pinned_to_another_engine():
    registry = EngineRegistry(
        Settings(
            _env_file=None,
            engine_routing_mode="split",
            comfy_image_url="https://image.example.test",
            comfy_video_url="https://video.example.test",
        )
    )

    with pytest.raises(RuntimeError, match="pinned to engine other-engine"):
        registry.require_pinned("other-engine", EngineCapability.image)


@pytest.mark.asyncio
async def test_comfy_client_accepts_an_explicit_engine_url():
    client = ComfyClient(Settings(_env_file=None), base_url="https://image.example.test")
    try:
        assert str(client.http.base_url) == "https://image.example.test"
    finally:
        await client.close()
