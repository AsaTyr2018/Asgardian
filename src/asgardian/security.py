import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Wall

CAPABILITY_HEADER = "X-Wall-Capability"


def new_capability() -> str:
    return secrets.token_urlsafe(32)


def hash_capability(capability: str) -> str:
    return hashlib.sha256(capability.encode()).hexdigest()


def asset_token(capability_hash: str, job_id: uuid.UUID) -> str:
    return hmac.new(bytes.fromhex(capability_hash), str(job_id).encode(), hashlib.sha256).hexdigest()


def verify_asset_token(capability_hash: str, job_id: uuid.UUID, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(asset_token(capability_hash, job_id), token)


async def verify_wall(
    wall_id: uuid.UUID,
    session: AsyncSession,
    capability: str | None,
) -> Wall:
    if not capability:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="wall capability required")
    wall = await session.scalar(select(Wall).where(Wall.id == wall_id))
    expires_at = wall.expires_at if wall else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if wall is None or expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="wall not found")
    if not hmac.compare_digest(wall.capability_hash, hash_capability(capability)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid wall capability")
    return wall
