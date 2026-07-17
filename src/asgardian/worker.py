import asyncio
import io
import logging
from datetime import UTC, datetime

from PIL import Image, ImageOps

from .comfy import ComfyClient, ComfyError, WorkflowRegistry
from .config import get_settings
from .db import SessionLocal, create_schema
from .engines import EngineCapability, EngineRegistry
from .events import event_bus
from .ltx import build_native_video_workflow, video_dimensions
from .models import GenerationFormat, GenerationJob, GenerationMode, JobStatus, SavedAsset, VideoJob
from .queue import claim_next_job, claim_next_video
from .storage import S3Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("asgardian.worker")

FORMAT_DIMENSIONS = {
    GenerationFormat.portrait: (896, 1152),
    GenerationFormat.square: (1024, 1024),
    GenerationFormat.landscape: (1152, 896),
}


def source_dimensions(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        oriented = ImageOps.exif_transpose(image)
        return oriented.size


def latent_dimension(value: int) -> int:
    """Return the closest VAE-compatible dimension."""
    return max(8, ((value + 4) // 8) * 8)


def restore_source_dimensions(
    data: bytes, content_type: str, expected_size: tuple[int, int] | None
) -> tuple[bytes, str]:
    if expected_size is None:
        return data, content_type
    with Image.open(io.BytesIO(data)) as image:
        oriented = ImageOps.exif_transpose(image)
        if oriented.size == expected_size and oriented is image:
            return data, content_type
        if oriented.size != expected_size:
            oriented = oriented.resize(expected_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        oriented.save(output, format="PNG")
        return output.getvalue(), "image/png"


class Worker:
    def __init__(self):
        self.settings = get_settings()
        self.storage = S3Storage(self.settings)
        self.workflows = WorkflowRegistry(self.settings.workflow_dir)
        self.engines = EngineRegistry(self.settings)

    async def process(self, job: GenerationJob) -> None:
        target = self.engines.require_pinned(job.engine_id, EngineCapability.image)
        comfy = ComfyClient(self.settings, base_url=target.url)
        try:
            source_name = None
            expected_size = None
            width, height = FORMAT_DIMENSIONS[job.generation_format or GenerationFormat.square]
            if job.source_object_key:
                source_data, source_type = await self.storage.get(job.source_object_key)
                expected_size = source_dimensions(source_data)
                width = latent_dimension(expected_size[0])
                height = latent_dimension(expected_size[1])
                source_name = await comfy.upload_image(source_data, f"asgardian-{job.id}.png", source_type)
            workflow_name = (
                "qwen-image-edit.api.json"
                if job.mode == GenerationMode.image_edit
                else "qwen-text-to-image.api.json"
            )
            workflow = self.workflows.render(
                workflow_name,
                prompt=job.prompt,
                negative_prompt=job.negative_prompt,
                seed=job.seed,
                source_image=source_name,
                width=width,
                height=height,
                output_prefix=f"Asgardian/{job.id}",
            )
            prompt_id = await comfy.submit(workflow)
            async with SessionLocal() as session:
                persisted = await session.get(GenerationJob, job.id)
                if persisted:
                    persisted.comfy_prompt_id = prompt_id
                    await session.commit()
            await event_bus.publish("wall.changed", job.wall_id)
            logger.info("job %s submitted to engine %s prompt_id=%s", job.id, target.id, prompt_id)
        except Exception as exc:
            logger.exception("job %s failed", job.id)
            async with SessionLocal() as session:
                persisted = await session.get(GenerationJob, job.id)
                if persisted:
                    persisted.status = JobStatus.failed
                    persisted.error_code = "comfy_error" if isinstance(exc, ComfyError) else "worker_error"
                    persisted.error_message = str(exc)[:1000]
                    persisted.completed_at = datetime.now(UTC)
                    await session.commit()
            await event_bus.publish("wall.changed", job.wall_id)
        finally:
            await comfy.close()

    async def process_video(self, job: VideoJob) -> None:
        target = self.engines.require_pinned(job.engine_id, EngineCapability.video)
        comfy = ComfyClient(self.settings, base_url=target.url)
        try:
            async with SessionLocal() as session:
                asset = await session.get(SavedAsset, job.saved_asset_id)
            if asset is None:
                raise RuntimeError("saved source image no longer exists")
            source_data, source_type = await self.storage.get(asset.object_key)
            source_width, source_height = source_dimensions(source_data)
            width, height = video_dimensions(source_width, source_height)
            source_name = await comfy.upload_image(source_data, f"asgardian-video-{job.id}.png", source_type)
            workflow = build_native_video_workflow(
                source_image=source_name,
                prompt=job.prompt,
                seed=job.seed,
                width=width,
                height=height,
                output_prefix=f"Asgardian/video/{job.id}",
            )
            prompt_id = await comfy.submit(workflow)
            async with SessionLocal() as session:
                persisted = await session.get(VideoJob, job.id)
                if persisted:
                    persisted.comfy_prompt_id = prompt_id
                    await session.commit()
            await event_bus.publish("video.changed")
            logger.info("video job %s submitted to engine %s prompt_id=%s", job.id, target.id, prompt_id)
        except Exception as exc:
            logger.exception("video job %s failed", job.id)
            async with SessionLocal() as session:
                persisted = await session.get(VideoJob, job.id)
                if persisted:
                    persisted.status = JobStatus.failed
                    persisted.error_code = "comfy_error" if isinstance(exc, ComfyError) else "worker_error"
                    persisted.error_message = str(exc)[:1000]
                    persisted.completed_at = datetime.now(UTC)
                    await session.commit()
            await event_bus.publish("video.changed")
        finally:
            await comfy.close()

    async def run_forever(self) -> None:
        await create_schema()
        image_target = self.engines.for_capability(EngineCapability.image)
        video_target = self.engines.for_capability(EngineCapability.video)
        logger.info(
            "dispatcher started with concurrency=1 routing=%s image_engine=%s video_engine=%s",
            self.engines.mode,
            image_target.id,
            video_target.id,
        )
        while True:
            async with SessionLocal() as session:
                job = await claim_next_job(session, image_target.id)
            if job is None:
                async with SessionLocal() as session:
                    video_job = await claim_next_video(session, video_target.id)
                if video_job is None:
                    await asyncio.sleep(self.settings.poll_interval_seconds)
                    continue
                await event_bus.publish("video.changed")
                await self.process_video(video_job)
            else:
                await event_bus.publish("wall.changed", job.wall_id)
                await self.process(job)


def run() -> None:
    asyncio.run(Worker().run_forever())


if __name__ == "__main__":
    run()
