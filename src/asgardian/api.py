import asyncio
import io
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import StreamingResponse

from .config import get_settings
from .db import SessionLocal, create_schema, session_dependency
from .events import event_bus
from .models import (
    GenerationFormat,
    GenerationJob,
    GenerationMode,
    JobStatus,
    SavedAsset,
    VideoJob,
    Wall,
)
from .schemas import (
    GenerationCreated,
    GenerationList,
    GenerationView,
    HealthResponse,
    LiveSnapshot,
    SavedAssetList,
    SavedAssetView,
    VideoCreated,
    VideoList,
    VideoView,
    WallCreated,
    WallHeartbeat,
)
from .security import (
    CAPABILITY_HEADER,
    asset_token,
    hash_capability,
    new_capability,
    verify_asset_token,
    verify_wall,
)
from .storage import S3Storage

settings = get_settings()
storage = S3Storage(settings)
logger = logging.getLogger("asgardian.api")


def prevent_dynamic_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_schema()
    try:
        yield
    finally:
        await event_bus.close()


app = FastAPI(title="Asgardian API", version="0.4.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", CAPABILITY_HEADER],
)


@app.get("/healthz", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/v1/walls", response_model=WallCreated, status_code=status.HTTP_201_CREATED)
async def create_wall(session: AsyncSession = Depends(session_dependency)) -> WallCreated:
    capability = new_capability()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.wall_ttl_seconds)
    wall = Wall(capability_hash=hash_capability(capability), expires_at=expires_at)
    session.add(wall)
    await session.commit()
    await session.refresh(wall)
    return WallCreated(id=wall.id, capability=capability, expires_at=wall.expires_at)


@app.post("/api/v1/walls/{wall_id}/heartbeat", response_model=WallHeartbeat)
async def heartbeat(
    wall_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> WallHeartbeat:
    wall = await verify_wall(wall_id, session, capability)
    now = datetime.now(UTC)
    wall.last_seen_at = now
    wall.expires_at = now + timedelta(seconds=settings.wall_ttl_seconds)
    await session.commit()
    return WallHeartbeat(expires_at=wall.expires_at)


async def validate_image(upload: UploadFile) -> tuple[bytes, str, str]:
    data = await upload.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image exceeds 20 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=422, detail="invalid image") from exc
    if not (256 <= width <= 4096 and 256 <= height <= 4096):
        raise HTTPException(status_code=422, detail="image dimensions must be between 256 and 4096 pixels")
    formats = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}
    if image_format not in formats:
        raise HTTPException(status_code=422, detail="only JPEG, PNG and WebP are supported")
    extension, content_type = formats[image_format]
    return data, extension, content_type


def view_for(job: GenerationJob, wall: Wall | None = None) -> GenerationView:
    result_url = None
    thumbnail_url = None
    download_url = None
    if job.result_object_key:
        suffix = f"?token={asset_token(wall.capability_hash, job.id)}" if wall else ""
        result_url = f"/api/v1/walls/{job.wall_id}/generations/{job.id}/asset{suffix}"
        thumbnail_url = f"/api/v1/walls/{job.wall_id}/generations/{job.id}/thumbnail{suffix}"
        download_url = f"/api/v1/walls/{job.wall_id}/generations/{job.id}/download{suffix}"
    return GenerationView.model_validate(job).model_copy(
        update={
            "result_url": result_url,
            "thumbnail_url": thumbnail_url,
            "download_url": download_url,
            "width": job.result_width,
            "height": job.result_height,
        }
    )


@app.post(
    "/api/v1/walls/{wall_id}/generations",
    response_model=GenerationCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation(
    wall_id: uuid.UUID,
    prompt: str = Form(min_length=1, max_length=2000),
    negative_prompt: str = Form(default="", max_length=2000),
    seed: int | None = Form(default=None, ge=0, le=2**63 - 1),
    count: int = Form(default=1, ge=1, le=8),
    generation_format: GenerationFormat = Form(default=GenerationFormat.square, alias="format"),
    image: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> GenerationCreated:
    await verify_wall(wall_id, session, capability)
    await session.scalar(select(Wall).where(Wall.id == wall_id).with_for_update())
    await session.execute(
        update(GenerationJob)
        .where(
            GenerationJob.wall_id == wall_id,
            GenerationJob.status == JobStatus.queued,
        )
        .values(
            status=JobStatus.cancelled,
            error_code="superseded",
            error_message="Superseded by a newer prompt",
            completed_at=datetime.now(UTC),
        )
    )
    batch_id = uuid.uuid4()
    source_key = None
    if image is not None:
        data, extension, content_type = await validate_image(image)
        source_key = f"transient/{wall_id}/sources/{batch_id}.{extension}"
        await storage.put(source_key, data, content_type)
    jobs = [
        GenerationJob(
            id=uuid.uuid4(),
            batch_id=batch_id,
            wall_id=wall_id,
            mode=GenerationMode.image_edit if source_key else GenerationMode.text_to_image,
            prompt=prompt.strip(),
            negative_prompt=negative_prompt.strip(),
            seed=seed if seed is not None and count == 1 else secrets.randbelow(2**63 - 1),
            generation_format=generation_format if source_key is None else None,
            source_object_key=source_key,
        )
        for _ in range(count)
    ]
    session.add_all(jobs)
    try:
        await session.commit()
    except Exception:
        if source_key:
            await storage.delete(source_key)
        raise
    await event_bus.publish("wall.changed", wall_id)
    first = jobs[0]
    return GenerationCreated(id=first.id, status=first.status, mode=first.mode, reserved=count)


@app.get("/api/v1/walls/{wall_id}/generations", response_model=GenerationList)
async def list_generations(
    wall_id: uuid.UUID,
    response: Response,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> GenerationList:
    prevent_dynamic_caching(response)
    wall = await verify_wall(wall_id, session, capability)
    jobs = (
        await session.scalars(
            select(GenerationJob)
            .where(
                GenerationJob.wall_id == wall_id,
                GenerationJob.status != JobStatus.cancelled,
            )
            .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
            .limit(100)
        )
    ).all()
    return GenerationList(items=[view_for(job, wall) for job in jobs])


@app.get("/api/v1/walls/{wall_id}/generations/{job_id}", response_model=GenerationView)
async def get_generation(
    wall_id: uuid.UUID,
    job_id: uuid.UUID,
    response: Response,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> GenerationView:
    prevent_dynamic_caching(response)
    wall = await verify_wall(wall_id, session, capability)
    job = await session.scalar(
        select(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.wall_id == wall_id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return view_for(job, wall)


@app.get("/api/v1/walls/{wall_id}/generations/{job_id}/asset")
async def get_asset(
    wall_id: uuid.UUID,
    job_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
    token: str | None = Query(default=None),
) -> Response:
    job = await session.scalar(
        select(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.wall_id == wall_id)
    )
    if job is None or not job.result_object_key:
        raise HTTPException(status_code=404, detail="asset not found")
    wall = await session.get(Wall, wall_id)
    if wall is None or not verify_asset_token(wall.capability_hash, job.id, token):
        await verify_wall(wall_id, session, capability)
    data, content_type = await storage.get(job.result_object_key)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, no-store"})


@app.get("/api/v1/walls/{wall_id}/generations/{job_id}/thumbnail")
async def get_generation_thumbnail(
    wall_id: uuid.UUID,
    job_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
    token: str | None = Query(default=None),
) -> Response:
    job = await session.scalar(
        select(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.wall_id == wall_id)
    )
    if job is None or not job.result_object_key:
        raise HTTPException(status_code=404, detail="thumbnail not found")
    wall = await session.get(Wall, wall_id)
    if wall is None or not verify_asset_token(wall.capability_hash, job.id, token):
        await verify_wall(wall_id, session, capability)
    data, content_type = await storage.get(job.thumbnail_object_key or job.result_object_key)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/v1/walls/{wall_id}/generations/{job_id}/download")
async def download_generation(
    wall_id: uuid.UUID,
    job_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
    token: str | None = Query(default=None),
) -> Response:
    response = await get_asset(wall_id, job_id, session, capability, token)
    response.headers["Content-Disposition"] = f'attachment; filename="asgardian-{job_id}.png"'
    return response


def saved_view(asset: SavedAsset) -> SavedAssetView:
    return SavedAssetView.model_validate(asset).model_copy(
        update={
            "asset_url": f"/api/v1/library/{asset.id}/asset",
            "thumbnail_url": f"/api/v1/library/{asset.id}/thumbnail",
            "download_url": f"/api/v1/library/{asset.id}/download",
        }
    )


@app.post(
    "/api/v1/walls/{wall_id}/generations/{job_id}/save",
    response_model=SavedAssetView,
    status_code=status.HTTP_201_CREATED,
)
async def save_generation(
    wall_id: uuid.UUID,
    job_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> SavedAssetView:
    await verify_wall(wall_id, session, capability)
    job = await session.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.wall_id == wall_id)
        .with_for_update()
    )
    if job is None or job.status != JobStatus.succeeded or not job.result_object_key:
        raise HTTPException(status_code=409, detail="only completed generations can be saved")
    existing = await session.scalar(select(SavedAsset).where(SavedAsset.source_generation_id == job.id))
    if existing is not None:
        return saved_view(existing)
    asset_id = uuid.uuid4()
    destination_key = f"persistent/library/{asset_id}/image.png"
    thumbnail_key = f"persistent/library/{asset_id}/thumbnail.webp" if job.thumbnail_object_key else None
    copied = await storage.copy(job.result_object_key, destination_key)
    if thumbnail_key and job.thumbnail_object_key:
        await storage.copy(job.thumbnail_object_key, thumbnail_key)
    asset = SavedAsset(
        id=asset_id,
        source_generation_id=job.id,
        mode=job.mode,
        prompt=job.prompt,
        seed=job.seed,
        object_key=destination_key,
        thumbnail_object_key=thumbnail_key,
        content_type=copied.content_type,
        generation_format=job.generation_format,
        width=job.result_width,
        height=job.result_height,
    )
    session.add(asset)
    try:
        await session.commit()
    except Exception:
        await storage.delete(destination_key)
        if thumbnail_key:
            await storage.delete(thumbnail_key)
        raise
    await session.refresh(asset)
    await event_bus.publish("library.changed")
    return saved_view(asset)


@app.get("/api/v1/library", response_model=SavedAssetList)
async def list_saved_assets(
    response: Response,
    session: AsyncSession = Depends(session_dependency),
) -> SavedAssetList:
    prevent_dynamic_caching(response)
    assets = (
        await session.scalars(select(SavedAsset).order_by(SavedAsset.created_at.desc()).limit(200))
    ).all()
    return SavedAssetList(items=[saved_view(asset) for asset in assets])


@app.get("/api/v1/library/{asset_id}/asset")
async def get_saved_asset(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
) -> Response:
    asset = await session.get(SavedAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="saved asset not found")
    data, content_type = await storage.get(asset.object_key)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/v1/library/{asset_id}/thumbnail")
async def get_saved_thumbnail(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
) -> Response:
    asset = await session.get(SavedAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="saved asset not found")
    data, content_type = await storage.get(asset.thumbnail_object_key or asset.object_key)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/v1/library/{asset_id}/download")
async def download_saved_asset(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
) -> Response:
    response = await get_saved_asset(asset_id, session)
    response.headers["Content-Disposition"] = f'attachment; filename="asgardian-saved-{asset_id}.png"'
    return response


@app.delete("/api/v1/library/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_asset(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
) -> Response:
    asset = await session.scalar(
        select(SavedAsset)
        .where(SavedAsset.id == asset_id)
        .options(selectinload(SavedAsset.videos))
        .with_for_update()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="saved asset not found")
    if any(video.status in (JobStatus.queued, JobStatus.running) for video in asset.videos):
        raise HTTPException(status_code=409, detail="image has an active video generation")

    object_keys = [asset.object_key]
    if asset.thumbnail_object_key:
        object_keys.append(asset.thumbnail_object_key)
    object_keys.extend(video.result_object_key for video in asset.videos if video.result_object_key)
    for object_key in object_keys:
        await storage.delete(object_key)

    await session.delete(asset)
    await session.commit()
    await event_bus.publish("library.changed")
    await event_bus.publish("video.changed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def video_view(job: VideoJob) -> VideoView:
    video_url = f"/api/v1/videos/{job.id}/asset" if job.result_object_key else None
    return VideoView.model_validate(job).model_copy(update={"video_url": video_url})


@app.post(
    "/api/v1/library/{asset_id}/videos",
    response_model=VideoCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_video(
    asset_id: uuid.UUID,
    prompt: str = Form(min_length=1, max_length=2000),
    seed: int | None = Form(default=None, ge=0, le=2**63 - 2),
    session: AsyncSession = Depends(session_dependency),
) -> VideoCreated:
    asset = await session.scalar(select(SavedAsset).where(SavedAsset.id == asset_id).with_for_update())
    if asset is None:
        raise HTTPException(status_code=404, detail="saved image not found")
    active = await session.scalar(
        select(VideoJob).where(
            VideoJob.saved_asset_id == asset_id,
            VideoJob.status.in_((JobStatus.queued, JobStatus.running)),
        )
    )
    if active is not None:
        return VideoCreated(id=active.id, status=active.status)
    job = VideoJob(
        saved_asset_id=asset_id,
        prompt=prompt.strip(),
        seed=seed if seed is not None else secrets.randbelow(2**63 - 2),
        fps=60,
        frame_count=721,
        duration_seconds=12,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await event_bus.publish("video.changed")
    return VideoCreated(id=job.id, status=job.status)


@app.get("/api/v1/videos", response_model=VideoList)
async def list_videos(
    response: Response,
    session: AsyncSession = Depends(session_dependency),
) -> VideoList:
    prevent_dynamic_caching(response)
    jobs = (await session.scalars(select(VideoJob).order_by(VideoJob.created_at.desc()).limit(200))).all()
    return VideoList(items=[video_view(job) for job in jobs])


@app.get("/api/v1/videos/{video_id}/asset")
async def get_video(
    video_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
) -> Response:
    job = await session.get(VideoJob, video_id)
    if job is None or not job.result_object_key:
        raise HTTPException(status_code=404, detail="video not found")
    data, content_type = await storage.get(job.result_object_key)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


async def live_snapshot(wall_id: uuid.UUID) -> LiveSnapshot | None:
    async with SessionLocal() as session:
        wall = await session.get(Wall, wall_id)
        if wall is None:
            return None
        jobs = (
            await session.scalars(
                select(GenerationJob)
                .where(
                    GenerationJob.wall_id == wall_id,
                    GenerationJob.status != JobStatus.cancelled,
                )
                .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
                .limit(100)
            )
        ).all()
        assets = (
            await session.scalars(select(SavedAsset).order_by(SavedAsset.created_at.desc()).limit(200))
        ).all()
        videos = (
            await session.scalars(select(VideoJob).order_by(VideoJob.created_at.desc()).limit(200))
        ).all()
        now = datetime.now(UTC)
        wall.last_seen_at = now
        wall.expires_at = now + timedelta(seconds=settings.wall_ttl_seconds)
        await session.commit()
        return LiveSnapshot(
            generations=[view_for(job, wall) for job in jobs],
            saved_assets=[saved_view(asset) for asset in assets],
            videos=[video_view(job) for job in videos],
        )


def sse_message(event: str, data: LiveSnapshot, event_id: str | None = None) -> str:
    identifier = f"id: {event_id}\n" if event_id else ""
    payload = json.dumps(data.model_dump(mode="json"), separators=(",", ":"))
    return f"{identifier}event: {event}\ndata: {payload}\n\n"


async def stream_wall(wall_id: uuid.UUID):
    try:
        cursor = await event_bus.cursor()
    except Exception:
        logger.exception("could not read initial Redis event cursor")
        cursor = "0-0"
    snapshot = await live_snapshot(wall_id)
    if snapshot is None:
        return
    yield "retry: 2000\n" + sse_message("snapshot", snapshot, cursor)
    while True:
        try:
            streams = await event_bus.read(cursor)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Redis stream read failed; retrying")
            await asyncio.sleep(2)
            snapshot = await live_snapshot(wall_id)
            if snapshot is None:
                return
            yield sse_message("snapshot", snapshot, cursor)
            continue
        relevant = not streams
        for _, entries in streams:
            for event_id, fields in entries:
                cursor = event_id
                topic = fields.get("topic", "")
                event_wall = fields.get("wall_id", "")
                if topic in {"library.changed", "video.changed"}:
                    relevant = True
                elif topic == "wall.changed" and event_wall == str(wall_id):
                    relevant = True
        if not relevant:
            yield ": keepalive\n\n"
            continue
        snapshot = await live_snapshot(wall_id)
        if snapshot is None:
            return
        yield sse_message("snapshot", snapshot, cursor)


@app.get("/api/v1/walls/{wall_id}/live")
async def live_wall(
    wall_id: uuid.UUID,
    session: AsyncSession = Depends(session_dependency),
    capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> StreamingResponse:
    await verify_wall(wall_id, session, capability)
    return StreamingResponse(
        stream_wall(wall_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def run() -> None:
    import uvicorn

    uvicorn.run("asgardian.api:app", host="0.0.0.0", port=8000)
