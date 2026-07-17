import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import get_settings
from .db import SessionLocal
from .models import GenerationJob, JobStatus, Wall
from .storage import S3Storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupResult:
    walls_deleted: int = 0
    walls_deferred: int = 0
    jobs_cancelled: int = 0
    objects_deleted: int = 0


async def cleanup_expired_walls(
    sessions: async_sessionmaker[AsyncSession],
    storage: S3Storage,
    *,
    now: datetime | None = None,
    batch_size: int = 100,
) -> CleanupResult:
    """Remove expired transient walls without interrupting a running GPU job."""
    now = now or datetime.now(UTC)
    async with sessions() as session:
        wall_ids = list(
            await session.scalars(
                select(Wall.id)
                .where(Wall.expires_at < now)
                .order_by(Wall.expires_at)
                .limit(batch_size)
            )
        )

    deleted = deferred = cancelled = objects_deleted = 0
    for wall_id in wall_ids:
        async with sessions() as session:
            wall = await session.scalar(
                select(Wall)
                .where(Wall.id == wall_id, Wall.expires_at < now)
                .with_for_update()
            )
            if wall is None:
                continue
            cancellation = await session.execute(
                update(GenerationJob)
                .where(
                    GenerationJob.wall_id == wall_id,
                    GenerationJob.status == JobStatus.queued,
                )
                .values(
                    status=JobStatus.cancelled,
                    error_code="wall_expired",
                    error_message="The transient wall expired before this job started.",
                    completed_at=now,
                    updated_at=now,
                )
            )
            cancelled += cancellation.rowcount or 0
            await session.refresh(wall, attribute_names=["jobs"])
            if any(job.status == JobStatus.running for job in wall.jobs):
                deferred += 1
                await session.commit()
                continue

            keys = {
                key
                for job in wall.jobs
                for key in (job.source_object_key, job.result_object_key, job.thumbnail_object_key)
                if key
            }
            for key in keys:
                await storage.delete(key)
                objects_deleted += 1

            await session.delete(wall)
            await session.commit()
            deleted += 1

    return CleanupResult(deleted, deferred, cancelled, objects_deleted)


async def cleanup_once() -> CleanupResult:
    settings = get_settings()
    return await cleanup_expired_walls(
        SessionLocal,
        S3Storage(settings),
        batch_size=settings.cleanup_batch_size,
    )


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = asyncio.run(cleanup_once())
    logger.info("transient cleanup complete: %s", asdict(result))
