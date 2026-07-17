import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asgardian.cleanup import cleanup_expired_walls
from asgardian.models import Base, GenerationJob, GenerationMode, JobStatus, Wall


class MemoryStorage:
    def __init__(self):
        self.objects: set[str] = set()

    async def delete(self, key: str) -> None:
        self.objects.discard(key)


@pytest.fixture
async def cleanup_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    storage = MemoryStorage()
    yield sessions, storage
    await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired_transient_wall_data(cleanup_context):
    sessions, storage = cleanup_context
    now = datetime.now(UTC)
    source_key = "transient/expired/source.png"
    result_key = "transient/expired/result.png"
    persistent_key = "persistent/library/kept/image.png"
    storage.objects.update({source_key, result_key, persistent_key})

    async with sessions() as session:
        expired = Wall(capability_hash="x" * 64, expires_at=now - timedelta(minutes=1))
        active = Wall(capability_hash="y" * 64, expires_at=now + timedelta(hours=1))
        session.add_all((expired, active))
        await session.flush()
        session.add_all(
            (
                GenerationJob(
                    id=uuid.uuid4(), wall_id=expired.id, mode=GenerationMode.text_to_image,
                    prompt="done", seed=1, status=JobStatus.succeeded,
                    source_object_key=source_key, result_object_key=result_key,
                ),
                GenerationJob(
                    id=uuid.uuid4(), wall_id=expired.id, mode=GenerationMode.text_to_image,
                    prompt="waiting", seed=2, status=JobStatus.queued,
                ),
            )
        )
        active_id = active.id
        await session.commit()

    result = await cleanup_expired_walls(sessions, storage, now=now)

    assert result.walls_deleted == 1
    assert result.jobs_cancelled == 1
    assert result.objects_deleted == 2
    assert storage.objects == {persistent_key}
    async with sessions() as session:
        assert list(await session.scalars(select(Wall.id))) == [active_id]
        assert list(await session.scalars(select(GenerationJob.id))) == []


@pytest.mark.asyncio
async def test_cleanup_defers_wall_with_running_job(cleanup_context):
    sessions, storage = cleanup_context
    now = datetime.now(UTC)
    storage.objects.add("transient/running/result.png")
    async with sessions() as session:
        wall = Wall(capability_hash="z" * 64, expires_at=now - timedelta(minutes=1))
        session.add(wall)
        await session.flush()
        session.add_all(
            (
                GenerationJob(
                    wall_id=wall.id, mode=GenerationMode.text_to_image, prompt="running", seed=1,
                    status=JobStatus.running, result_object_key="transient/running/result.png",
                ),
                GenerationJob(
                    wall_id=wall.id, mode=GenerationMode.text_to_image, prompt="queued", seed=2,
                    status=JobStatus.queued,
                ),
            )
        )
        wall_id = wall.id
        await session.commit()

    result = await cleanup_expired_walls(sessions, storage, now=now)

    assert result.walls_deleted == 0
    assert result.walls_deferred == 1
    assert result.jobs_cancelled == 1
    assert storage.objects == {"transient/running/result.png"}
    async with sessions() as session:
        assert await session.get(Wall, wall_id) is not None
        statuses = set(await session.scalars(select(GenerationJob.status)))
        assert statuses == {JobStatus.running, JobStatus.cancelled}
