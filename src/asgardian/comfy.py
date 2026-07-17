import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import Settings, get_settings


class ComfyError(RuntimeError):
    pass


def replace_placeholders(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: replace_placeholders(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_placeholders(item, replacements) for item in value]
    return replacements.get(value, value)


class WorkflowRegistry:
    def __init__(self, directory: Path):
        self.directory = directory

    def load(self, name: str) -> dict[str, Any]:
        path = self.directory / name
        if path.parent.resolve() != self.directory.resolve():
            raise ComfyError("invalid workflow path")
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def render(
        self,
        name: str,
        *,
        prompt: str,
        negative_prompt: str,
        seed: int,
        output_prefix: str,
        source_image: str | None = None,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        template = self.load(name)
        rendered = replace_placeholders(
            template,
            {
                "${PROMPT}": prompt,
                "${NEGATIVE_PROMPT}": negative_prompt,
                "${SEED}": seed,
                "${OUTPUT_PREFIX}": output_prefix,
                "${SOURCE_IMAGE}": source_image,
                "${WIDTH}": width,
                "${HEIGHT}": height,
            },
        )
        serialized = json.dumps(rendered)
        if "${" in serialized:
            raise ComfyError("workflow contains unresolved placeholders")
        return rendered


class ComfyClient:
    def __init__(self, settings: Settings | None = None, *, base_url: str | None = None):
        self.settings = settings or get_settings()
        self.client_id = str(uuid.uuid4())
        self.http = httpx.AsyncClient(base_url=base_url or self.settings.comfy_url, timeout=60)

    async def close(self) -> None:
        await self.http.aclose()

    async def upload_image(self, data: bytes, filename: str, content_type: str) -> str:
        response = await self.http.post(
            "/upload/image",
            files={"image": (filename, data, content_type)},
            data={"type": "input", "overwrite": "false"},
        )
        response.raise_for_status()
        result = response.json()
        return "/".join(part for part in (result.get("subfolder"), result["name"]) if part)

    async def submit(self, workflow: dict[str, Any]) -> str:
        response = await self.http.post("/prompt", json={"prompt": workflow, "client_id": self.client_id})
        if response.status_code >= 400:
            raise ComfyError(f"ComfyUI rejected workflow: {response.text[:500]}")
        result = response.json()
        if "prompt_id" not in result:
            raise ComfyError("ComfyUI response did not contain prompt_id")
        return result["prompt_id"]

    async def wait(self, prompt_id: str, timeout_seconds: int = 600) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            response = await self.http.get(f"/history/{prompt_id}")
            response.raise_for_status()
            entry = response.json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError("ComfyUI workflow failed")
                if status.get("completed") or status.get("status_str") == "success":
                    return entry
            await asyncio.sleep(self.settings.poll_interval_seconds)
        raise ComfyError(f"ComfyUI prompt {prompt_id} timed out")

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        response = await self.http.get(f"/history/{prompt_id}")
        response.raise_for_status()
        entry = response.json().get(prompt_id)
        if not entry:
            return None
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise ComfyError("ComfyUI workflow failed")
        if status.get("completed") or status.get("status_str") == "success":
            return entry
        return None

    async def download_first_output(self, entry: dict[str, Any]) -> tuple[bytes, str]:
        for output in entry.get("outputs", {}).values():
            for image in output.get("images", []):
                response = await self.http.get(
                    "/view",
                    params={
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    },
                )
                response.raise_for_status()
                return response.content, response.headers.get("content-type", "image/png")
        raise ComfyError("ComfyUI history contained no output image")

    async def download_first_video(self, entry: dict[str, Any]) -> tuple[bytes, str]:
        for output in entry.get("outputs", {}).values():
            for key in ("videos", "video", "gifs", "images"):
                items = output.get(key, [])
                if isinstance(items, dict):
                    items = [items]
                for media in items:
                    filename = str(media.get("filename", ""))
                    if not filename.lower().endswith((".mp4", ".webm", ".mkv")):
                        continue
                    response = await self.http.get(
                        "/view",
                        params={
                            "filename": filename,
                            "subfolder": media.get("subfolder", ""),
                            "type": media.get("type", "output"),
                        },
                    )
                    response.raise_for_status()
                    return response.content, response.headers.get("content-type", "video/mp4")
        raise ComfyError("ComfyUI history contained no output video")
