import asyncio
import logging
import subprocess
import tempfile
from datetime import UTC, datetime

from sqlalchemy import select

from .comfy import ComfyClient, ComfyError
from .config import get_settings
from .db import SessionLocal, create_schema
from .engines import EngineCapability, EngineRegistry
from .events import event_bus
from .media import create_thumbnail, image_dimensions
from .models import GenerationJob, JobStatus, VideoJob
from .storage import S3Storage
from .worker import restore_source_dimensions, source_dimensions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("asgardian.reconciler")


def trim_native_video(data: bytes) -> bytes:
    """Drop LTX's terminal 721st frame; no interpolation is performed."""
    with tempfile.TemporaryDirectory(prefix="asgardian-video-") as directory:
        source = f"{directory}/native.mp4"
        destination = f"{directory}/exact.mp4"
        with open(source, "wb") as handle:
            handle.write(data)
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", source,
                "-filter_complex",
                "[0:v]trim=end_frame=720,setpts=PTS-STARTPTS[v];[0:a]atrim=duration=12,asetpts=PTS-STARTPTS[a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "slow",
                "-crf", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", destination,
            ],
            check=True,
            timeout=180,
        )
        with open(destination, "rb") as handle:
            return handle.read()


class Reconciler:
    def __init__(self):
        self.settings = get_settings()
        self.storage = S3Storage(self.settings)
        self.engines = EngineRegistry(self.settings)

    async def fail_image(self, job: GenerationJob, exc: Exception) -> None:
        async with SessionLocal() as session:
            persisted = await session.get(GenerationJob, job.id)
            if persisted and persisted.status == JobStatus.running:
                persisted.status = JobStatus.failed
                persisted.error_code = "comfy_error"
                persisted.error_message = str(exc)[:1000]
                persisted.completed_at = datetime.now(UTC)
                await session.commit()
        await event_bus.publish("wall.changed", job.wall_id)

    async def reconcile_image(self, job: GenerationJob) -> None:
        target = self.engines.require_pinned(job.engine_id, EngineCapability.image)
        comfy = ComfyClient(self.settings, base_url=target.url)
        try:
            entry = await comfy.history(job.comfy_prompt_id or "")
            if entry is None:
                return
            result, content_type = await comfy.download_first_output(entry)
            expected_size = None
            if job.source_object_key:
                source_data, _ = await self.storage.get(job.source_object_key)
                expected_size = source_dimensions(source_data)
            result, content_type = restore_source_dimensions(result, content_type, expected_size)
            width, height = image_dimensions(result)
            thumbnail = create_thumbnail(result)
            result_key = f"transient/{job.wall_id}/{job.id}/result.png"
            thumbnail_key = f"transient/{job.wall_id}/{job.id}/thumbnail.webp"
            await self.storage.put(result_key, result, content_type)
            await self.storage.put(thumbnail_key, thumbnail, "image/webp")
            async with SessionLocal() as session:
                persisted = await session.get(GenerationJob, job.id)
                if persisted and persisted.status == JobStatus.running:
                    persisted.result_object_key = result_key
                    persisted.thumbnail_object_key = thumbnail_key
                    persisted.result_width = width
                    persisted.result_height = height
                    persisted.status = JobStatus.succeeded
                    persisted.completed_at = datetime.now(UTC)
                    await session.commit()
            await event_bus.publish("wall.changed", job.wall_id)
            logger.info("job %s finalized from engine %s", job.id, target.id)
        except ComfyError as exc:
            logger.exception("ComfyUI failed image job %s", job.id)
            await self.fail_image(job, exc)
        except Exception:
            logger.exception("transient image reconciliation error for job %s; will retry", job.id)
        finally:
            await comfy.close()

    async def fail_video(self, job: VideoJob, exc: Exception) -> None:
        async with SessionLocal() as session:
            persisted = await session.get(VideoJob, job.id)
            if persisted and persisted.status == JobStatus.running:
                persisted.status = JobStatus.failed
                persisted.error_code = "comfy_error"
                persisted.error_message = str(exc)[:1000]
                persisted.completed_at = datetime.now(UTC)
                await session.commit()
        await event_bus.publish("video.changed")

    async def reconcile_video(self, job: VideoJob) -> None:
        target = self.engines.require_pinned(job.engine_id, EngineCapability.video)
        comfy = ComfyClient(self.settings, base_url=target.url)
        try:
            entry = await comfy.history(job.comfy_prompt_id or "")
            if entry is None:
                return
            native_video, _ = await comfy.download_first_video(entry)
            result = await asyncio.to_thread(trim_native_video, native_video)
            result_key = f"persistent/library/{job.saved_asset_id}/videos/{job.id}.mp4"
            await self.storage.put(result_key, result, "video/mp4")
            async with SessionLocal() as session:
                persisted = await session.get(VideoJob, job.id)
                if persisted and persisted.status == JobStatus.running:
                    persisted.result_object_key = result_key
                    persisted.status = JobStatus.succeeded
                    persisted.completed_at = datetime.now(UTC)
                    await session.commit()
            await event_bus.publish("video.changed")
            logger.info("video job %s finalized from engine %s", job.id, target.id)
        except ComfyError as exc:
            logger.exception("ComfyUI failed video job %s", job.id)
            await self.fail_video(job, exc)
        except Exception:
            logger.exception("transient video reconciliation error for job %s; will retry", job.id)
        finally:
            await comfy.close()

    async def run_forever(self) -> None:
        await create_schema()
        logger.info("reconciler started interval=%ss", self.settings.poll_interval_seconds)
        while True:
            async with SessionLocal() as session:
                images = (
                    await session.scalars(
                        select(GenerationJob).where(
                            GenerationJob.status == JobStatus.running,
                            GenerationJob.comfy_prompt_id.is_not(None),
                        )
                    )
                ).all()
                videos = (
                    await session.scalars(
                        select(VideoJob).where(
                            VideoJob.status == JobStatus.running,
                            VideoJob.comfy_prompt_id.is_not(None),
                        )
                    )
                ).all()
            for job in images:
                await self.reconcile_image(job)
            for job in videos:
                await self.reconcile_video(job)
            await asyncio.sleep(self.settings.poll_interval_seconds)


def run() -> None:
    asyncio.run(Reconciler().run_forever())


if __name__ == "__main__":
    run()
