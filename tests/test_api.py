import io
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asgardian import api
from asgardian.db import session_dependency
from asgardian.models import Base, GenerationJob, JobStatus, VideoJob
from asgardian.storage import StoredObject


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    async def put(self, key, data, content_type):
        self.objects[key] = (data, content_type)
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key):
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(key, None)

    async def copy(self, source_key, destination_key):
        data, content_type = self.objects[source_key]
        self.objects[destination_key] = (data, content_type)
        return StoredObject(key=destination_key, size=len(data), content_type=content_type)


@pytest.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_session():
        async with sessions() as session:
            yield session

    storage = MemoryStorage()
    storage.sessions = sessions
    monkeypatch.setattr(api, "storage", storage)
    monkeypatch.setattr(api.event_bus, "publish", AsyncMock())
    api.app.dependency_overrides[session_dependency] = override_session
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as test_client:
        yield test_client, storage
    api.app.dependency_overrides.clear()
    await engine.dispose()


async def create_wall(client):
    response = await client.post("/api/v1/walls")
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_wall_capability_and_text_generation(client):
    http, _ = client
    wall = await create_wall(http)
    path = f"/api/v1/walls/{wall['id']}/generations"
    assert (await http.get(path)).status_code == 403

    response = await http.post(
        path,
        headers={"X-Wall-Capability": wall["capability"]},
        data={"prompt": "A quiet gate under northern lights"},
    )
    assert response.status_code == 202
    assert response.json()["mode"] == "text_to_image"
    listing = await http.get(path, headers={"X-Wall-Capability": wall["capability"]})
    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "no-store, max-age=0"
    assert listing.headers["pragma"] == "no-cache"
    assert listing.json()["items"][0]["status"] == "queued"
    assert listing.json()["items"][0]["generation_format"] == "square"


@pytest.mark.asyncio
async def test_text_generation_accepts_landscape_format(client):
    http, _ = client
    wall = await create_wall(http)
    path = f"/api/v1/walls/{wall['id']}/generations"
    headers = {"X-Wall-Capability": wall["capability"]}

    response = await http.post(
        path,
        headers=headers,
        data={"prompt": "A wide northern landscape", "format": "landscape"},
    )

    assert response.status_code == 202
    listing = (await http.get(path, headers=headers)).json()["items"]
    assert listing[0]["generation_format"] == "landscape"


@pytest.mark.asyncio
async def test_upload_selects_image_edit_without_mode_switch(client):
    http, storage = client
    wall = await create_wall(http)
    image = Image.new("RGB", (512, 512), color=(30, 90, 160))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    response = await http.post(
        f"/api/v1/walls/{wall['id']}/generations",
        headers={"X-Wall-Capability": wall["capability"]},
        data={"prompt": "Change only the background", "format": "landscape"},
        files={"image": ("source.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 202
    assert response.json()["mode"] == "image_edit"
    assert len(storage.objects) == 1
    listing = (
        await http.get(
            f"/api/v1/walls/{wall['id']}/generations",
            headers={"X-Wall-Capability": wall["capability"]},
        )
    ).json()["items"]
    assert listing[0]["generation_format"] is None


@pytest.mark.asyncio
async def test_new_prompt_keeps_running_job_and_supersedes_queued_jobs(client):
    http, storage = client
    wall = await create_wall(http)
    path = f"/api/v1/walls/{wall['id']}/generations"
    headers = {"X-Wall-Capability": wall["capability"]}

    response = await http.post(path, headers=headers, data={"prompt": "Eight northern gates", "count": 8})
    assert response.status_code == 202
    assert response.json()["reserved"] == 8

    async with storage.sessions() as session:
        original_jobs = (
            await session.scalars(select(GenerationJob).where(GenerationJob.wall_id == uuid.UUID(wall["id"])))
        ).all()
        original_jobs[0].status = JobStatus.running
        await session.commit()

    replacement = await http.post(
        path,
        headers=headers,
        data={"prompt": "A new golden gate", "count": 8},
    )
    assert replacement.status_code == 202
    assert replacement.json()["reserved"] == 8

    listing = (await http.get(path, headers=headers)).json()["items"]
    assert len(listing) == 9
    assert sum(item["status"] == "running" for item in listing) == 1
    assert sum(item["prompt"] == "A new golden gate" for item in listing) == 8

    async with storage.sessions() as session:
        all_jobs = (
            await session.scalars(select(GenerationJob).where(GenerationJob.wall_id == uuid.UUID(wall["id"])))
        ).all()
    assert sum(job.status == JobStatus.cancelled for job in all_jobs) == 7
    assert sum(job.status == JobStatus.running for job in all_jobs) == 1
    assert sum(job.status == JobStatus.queued for job in all_jobs) == 8
    assert next(job for job in all_jobs if job.status == JobStatus.running).prompt == "Eight northern gates"


@pytest.mark.asyncio
async def test_save_promotes_result_to_persistent_library_idempotently(client):
    http, storage = client
    wall = await create_wall(http)
    path = f"/api/v1/walls/{wall['id']}/generations"
    headers = {"X-Wall-Capability": wall["capability"]}
    created = (await http.post(path, headers=headers, data={"prompt": "A persistent gate"})).json()

    result_key = f"transient/{wall['id']}/{created['id']}/result.png"
    thumbnail_key = f"transient/{wall['id']}/{created['id']}/thumbnail.webp"
    storage.objects[result_key] = (b"saved-image", "image/png")
    storage.objects[thumbnail_key] = (b"saved-thumbnail", "image/webp")
    async with storage.sessions() as session:
        job = await session.scalar(select(GenerationJob).where(GenerationJob.id == uuid.UUID(created["id"])))
        job.status = JobStatus.succeeded
        job.result_object_key = result_key
        job.thumbnail_object_key = thumbnail_key
        job.result_width = 1024
        job.result_height = 1024
        await session.commit()

    listing = (await http.get(path, headers=headers)).json()["items"]
    assert listing[0]["width"] == 1024
    assert listing[0]["height"] == 1024
    assert "token=" in listing[0]["thumbnail_url"]
    assert (await http.get(listing[0]["thumbnail_url"])).content == b"saved-thumbnail"
    assert (await http.get(listing[0]["result_url"])).content == b"saved-image"
    assert (await http.get(listing[0]["download_url"])).headers["content-disposition"].startswith(
        "attachment;"
    )
    assert (await http.get(listing[0]["result_url"].split("?")[0] + "?token=invalid")).status_code == 403

    save_path = f"{path}/{created['id']}/save"
    first = await http.post(save_path, headers=headers)
    second = await http.post(save_path, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    library = (await http.get("/api/v1/library")).json()["items"]
    assert len(library) == 1
    assert library[0]["width"] == 1024
    assert library[0]["height"] == 1024
    asset = await http.get(library[0]["asset_url"])
    assert asset.status_code == 200
    assert asset.content == b"saved-image"
    assert (await http.get(library[0]["thumbnail_url"])).content == b"saved-thumbnail"
    assert (await http.get(library[0]["download_url"])).headers["content-disposition"].startswith(
        "attachment;"
    )
    assert len(storage.objects) == 4


@pytest.mark.asyncio
async def test_saved_image_can_queue_one_native_video_idempotently(client):
    http, storage = client
    wall = await create_wall(http)
    path = f"/api/v1/walls/{wall['id']}/generations"
    headers = {"X-Wall-Capability": wall["capability"]}
    created = (await http.post(path, headers=headers, data={"prompt": "A dancer"})).json()
    result_key = f"transient/{wall['id']}/{created['id']}/result.png"
    storage.objects[result_key] = (b"saved-image", "image/png")
    async with storage.sessions() as session:
        job = await session.get(GenerationJob, uuid.UUID(created["id"]))
        job.status = JobStatus.succeeded
        job.result_object_key = result_key
        await session.commit()
    saved = (await http.post(f"{path}/{created['id']}/save", headers=headers)).json()

    first = await http.post(f"/api/v1/library/{saved['id']}/videos", data={"prompt": "Dance with both arms"})
    second = await http.post(f"/api/v1/library/{saved['id']}/videos", data={"prompt": "Ignored duplicate"})

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    listing = (await http.get("/api/v1/videos")).json()["items"]
    assert len(listing) == 1
    assert listing[0]["fps"] == 60
    assert listing[0]["frame_count"] == 721
    assert listing[0]["duration_seconds"] == 12
    async with storage.sessions() as session:
        persisted = await session.get(VideoJob, uuid.UUID(first.json()["id"]))
        assert persisted is not None
        assert persisted.status == JobStatus.queued


@pytest.mark.asyncio
async def test_saved_image_delete_removes_image_videos_and_database_records(client):
    http, storage = client
    wall = await create_wall(http)
    path = f"/api/v1/walls/{wall['id']}/generations"
    headers = {"X-Wall-Capability": wall["capability"]}
    created = (await http.post(path, headers=headers, data={"prompt": "A disposable rune"})).json()
    result_key = f"transient/{wall['id']}/{created['id']}/result.png"
    storage.objects[result_key] = (b"generated-image", "image/png")
    async with storage.sessions() as session:
        job = await session.get(GenerationJob, uuid.UUID(created["id"]))
        job.status = JobStatus.succeeded
        job.result_object_key = result_key
        await session.commit()
    saved = (await http.post(f"{path}/{created['id']}/save", headers=headers)).json()
    video_id = uuid.uuid4()
    video_key = f"persistent/library/{saved['id']}/videos/{video_id}.mp4"
    storage.objects[video_key] = (b"video", "video/mp4")
    async with storage.sessions() as session:
        session.add(
            VideoJob(
                id=video_id,
                saved_asset_id=uuid.UUID(saved["id"]),
                status=JobStatus.succeeded,
                prompt="Rotate",
                seed=5,
                result_object_key=video_key,
            )
        )
        await session.commit()

    response = await http.delete(f"/api/v1/library/{saved['id']}")

    assert response.status_code == 204
    assert (await http.get("/api/v1/library")).json()["items"] == []
    assert (await http.get(saved["asset_url"])).status_code == 404
    assert result_key in storage.objects
    assert all(not key.startswith(f"persistent/library/{saved['id']}") for key in storage.objects)
    async with storage.sessions() as session:
        assert await session.get(VideoJob, video_id) is None


@pytest.mark.asyncio
async def test_saved_image_delete_is_blocked_while_video_is_active(client):
    http, storage = client
    wall = await create_wall(http)
    path = f"/api/v1/walls/{wall['id']}/generations"
    headers = {"X-Wall-Capability": wall["capability"]}
    created = (await http.post(path, headers=headers, data={"prompt": "A dancing rune"})).json()
    result_key = f"transient/{wall['id']}/{created['id']}/result.png"
    storage.objects[result_key] = (b"saved-image", "image/png")
    async with storage.sessions() as session:
        job = await session.get(GenerationJob, uuid.UUID(created["id"]))
        job.status = JobStatus.succeeded
        job.result_object_key = result_key
        await session.commit()
    saved = (await http.post(f"{path}/{created['id']}/save", headers=headers)).json()
    await http.post(f"/api/v1/library/{saved['id']}/videos", data={"prompt": "Dance"})

    response = await http.delete(f"/api/v1/library/{saved['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == "image has an active video generation"
    assert len((await http.get("/api/v1/library")).json()["items"]) == 1
