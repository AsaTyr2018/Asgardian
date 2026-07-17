"""Explicit ComfyUI engine routing with reversible solo and split modes."""

from dataclasses import dataclass
from enum import StrEnum

from .config import EngineRoutingMode, Settings


class EngineCapability(StrEnum):
    image = "image"
    video = "video"


@dataclass(frozen=True, slots=True)
class EngineTarget:
    id: str
    url: str
    capability: EngineCapability


class EngineRegistry:
    """Resolve exactly one configured engine for each capability.

    There is intentionally no fallback list: routing is either fully solo or
    fully split, and every claimed job is pinned to the selected target.
    """

    def __init__(self, settings: Settings):
        if settings.engine_routing_mode == EngineRoutingMode.solo:
            self._targets = {
                EngineCapability.image: EngineTarget(
                    id="primary", url=settings.comfy_url, capability=EngineCapability.image
                ),
                EngineCapability.video: EngineTarget(
                    id="primary", url=settings.comfy_url, capability=EngineCapability.video
                ),
            }
        else:
            if settings.comfy_image_url is None or settings.comfy_video_url is None:
                raise ValueError("split engine URLs were not validated")
            self._targets = {
                EngineCapability.image: EngineTarget(
                    id="image-engine",
                    url=settings.comfy_image_url,
                    capability=EngineCapability.image,
                ),
                EngineCapability.video: EngineTarget(
                    id="video-engine",
                    url=settings.comfy_video_url,
                    capability=EngineCapability.video,
                ),
            }

    @property
    def mode(self) -> EngineRoutingMode:
        image = self._targets[EngineCapability.image]
        video = self._targets[EngineCapability.video]
        return EngineRoutingMode.solo if image.id == video.id else EngineRoutingMode.split

    def for_capability(self, capability: EngineCapability) -> EngineTarget:
        return self._targets[capability]

    def require_pinned(self, engine_id: str | None, capability: EngineCapability) -> EngineTarget:
        target = self.for_capability(capability)
        if engine_id != target.id:
            raise RuntimeError(
                f"job is pinned to engine {engine_id or '<none>'}, configured engine is {target.id}"
            )
        return target
