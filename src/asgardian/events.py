import logging
import uuid

from redis.asyncio import Redis

from .config import Settings, get_settings

logger = logging.getLogger("asgardian.events")
STREAM_KEY = "asgardian:events"


class EventBus:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.redis = Redis.from_url(
            self.settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=20,
            health_check_interval=30,
        )

    async def publish(self, topic: str, wall_id: uuid.UUID | None = None) -> None:
        fields = {"topic": topic, "wall_id": str(wall_id) if wall_id else ""}
        try:
            await self.redis.xadd(
                STREAM_KEY,
                fields,
                maxlen=self.settings.event_stream_max_length,
                approximate=True,
            )
        except Exception:
            logger.exception("could not publish event topic=%s wall_id=%s", topic, wall_id)

    async def read(self, cursor: str, block_ms: int = 15_000):
        return await self.redis.xread({STREAM_KEY: cursor}, block=block_ms, count=100)

    async def cursor(self) -> str:
        latest = await self.redis.xrevrange(STREAM_KEY, count=1)
        return latest[0][0] if latest else "0-0"

    async def close(self) -> None:
        await self.redis.aclose()


event_bus = EventBus()
