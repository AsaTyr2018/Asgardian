from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GenerationJob, JobStatus, VideoJob


async def claim_next_job(session: AsyncSession, engine_id: str | None = None) -> GenerationJob | None:
    async with session.begin():
        running = await session.scalar(
            select(GenerationJob.id).where(GenerationJob.status == JobStatus.running).limit(1)
        )
        if running is not None:
            return None
        job = await session.scalar(
            select(GenerationJob)
            .where(GenerationJob.status == JobStatus.queued)
            .order_by(GenerationJob.created_at, GenerationJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is not None:
            if job.engine_id not in (None, engine_id):
                raise RuntimeError(f"queued image job is already pinned to {job.engine_id}")
            job.engine_id = engine_id
            job.status = JobStatus.running
            job.started_at = datetime.now(UTC)
    return job


async def claim_next_video(session: AsyncSession, engine_id: str | None = None) -> VideoJob | None:
    async with session.begin():
        running = await session.scalar(
            select(VideoJob.id).where(VideoJob.status == JobStatus.running).limit(1)
        )
        if running is not None:
            return None
        job = await session.scalar(
            select(VideoJob)
            .where(VideoJob.status == JobStatus.queued)
            .order_by(VideoJob.created_at, VideoJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is not None:
            if job.engine_id not in (None, engine_id):
                raise RuntimeError(f"queued video job is already pinned to {job.engine_id}")
            job.engine_id = engine_id
            job.status = JobStatus.running
            job.started_at = datetime.now(UTC)
    return job
