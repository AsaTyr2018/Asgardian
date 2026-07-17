export type Wall = { id: string; capability: string; expires_at: string };
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type GenerationFormat = "portrait" | "square" | "landscape";
export type Generation = {
  id: string;
  batch_id: string | null;
  wall_id: string;
  status: JobStatus;
  mode: "text_to_image" | "image_edit";
  generation_format: GenerationFormat | null;
  prompt: string;
  seed: number;
  created_at: string;
  completed_at: string | null;
  result_url: string | null;
  thumbnail_url?: string | null;
  download_url?: string | null;
  width?: number | null;
  height?: number | null;
  error_message: string | null;
};

export type SavedAsset = {
  id: string;
  source_generation_id: string;
  mode: "text_to_image" | "image_edit";
  prompt: string;
  seed: number;
  generation_format?: GenerationFormat | null;
  width?: number | null;
  height?: number | null;
  created_at: string;
  asset_url: string;
  thumbnail_url?: string;
  download_url?: string;
};

export type LiveSnapshot = {
  generations: Generation[];
  saved_assets: SavedAsset[];
  videos: VideoJob[];
};

export type VideoJob = {
  id: string;
  saved_asset_id: string;
  status: JobStatus;
  prompt: string;
  seed: number;
  fps: number;
  frame_count: number;
  duration_seconds: number;
  created_at: string;
  completed_at: string | null;
  video_url: string | null;
  error_message: string | null;
};

async function checked(response: Response): Promise<Response> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `Request failed with ${response.status}`);
  }
  return response;
}

export async function createWall(): Promise<Wall> {
  return checked(await fetch("/api/v1/walls", { method: "POST" })).then((response) => response.json());
}

export async function heartbeatWall(wall: Wall): Promise<void> {
  await checked(
    await fetch(`/api/v1/walls/${wall.id}/heartbeat`, {
      method: "POST",
      headers: { "X-Wall-Capability": wall.capability },
    }),
  );
}

export async function submitGeneration(
  wall: Wall,
  prompt: string,
  image: File | null,
  format: GenerationFormat,
  count = 8,
): Promise<void> {
  const form = new FormData();
  form.set("prompt", prompt);
  if (image) form.set("image", image);
  form.set("format", format);
  form.set("count", String(count));
  await checked(
    await fetch(`/api/v1/walls/${wall.id}/generations`, {
      method: "POST",
      headers: { "X-Wall-Capability": wall.capability },
      body: form,
    }),
  );
}

export async function saveGeneration(wall: Wall, generation: Generation): Promise<SavedAsset> {
  return checked(
    await fetch(`/api/v1/walls/${wall.id}/generations/${generation.id}/save`, {
      method: "POST",
      headers: { "X-Wall-Capability": wall.capability },
    }),
  ).then((response) => response.json());
}

export async function cancelGeneration(wall: Wall, generation: Generation): Promise<void> {
  await checked(
    await fetch(`/api/v1/walls/${wall.id}/generations/${generation.id}`, {
      method: "DELETE",
      headers: { "X-Wall-Capability": wall.capability },
    }),
  );
}

export async function pruneQueue(wall: Wall): Promise<number> {
  const response = await checked(
    await fetch(`/api/v1/walls/${wall.id}/generations/queue`, {
      method: "DELETE",
      headers: { "X-Wall-Capability": wall.capability },
    }),
  );
  return (await response.json()).cancelled;
}

export async function listSavedAssets(): Promise<SavedAsset[]> {
  return checked(await fetch("/api/v1/library", { cache: "no-store" }))
    .then(async (response) => (await response.json()).items);
}

export async function loadSavedAsset(asset: SavedAsset): Promise<Blob> {
  return checked(await fetch(asset.asset_url)).then((response) => response.blob());
}

export async function deleteSavedAsset(asset: SavedAsset): Promise<void> {
  await checked(await fetch(`/api/v1/library/${asset.id}`, { method: "DELETE" }));
}

export async function createVideo(asset: SavedAsset, prompt: string): Promise<void> {
  const form = new FormData();
  form.set("prompt", prompt);
  await checked(await fetch(`/api/v1/library/${asset.id}/videos`, { method: "POST", body: form }));
}

export async function listVideos(): Promise<VideoJob[]> {
  return checked(await fetch("/api/v1/videos", { cache: "no-store" }))
    .then(async (response) => (await response.json()).items);
}

async function timedFetch(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = 15_000): Promise<Response> {
  const controller = new AbortController();
  const relayAbort = () => controller.abort();
  init.signal?.addEventListener("abort", relayAbort, { once: true });
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timeout);
    init.signal?.removeEventListener("abort", relayAbort);
  }
}

export async function listGenerations(wall: Wall, signal?: AbortSignal): Promise<Generation[]> {
  const response = await checked(
    await timedFetch(`/api/v1/walls/${wall.id}/generations`, {
      cache: "no-store",
      headers: { "X-Wall-Capability": wall.capability },
      signal,
    }),
  );
  return (await response.json()).items;
}

export async function loadAsset(wall: Wall, generation: Generation): Promise<Blob> {
  void wall;
  const response = await checked(
    await timedFetch(generation.result_url!, {
      cache: "no-store",
    }, 20_000),
  );
  return response.blob();
}

function parseSseBlock(block: string): LiveSnapshot | null {
  const event = block.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim();
  if (event !== "snapshot") return null;
  const data = block.split("\n").filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart()).join("\n");
  return data ? JSON.parse(data) as LiveSnapshot : null;
}

export async function subscribeWall(
  wall: Wall,
  onSnapshot: (snapshot: LiveSnapshot) => void,
  signal: AbortSignal,
): Promise<void> {
  while (!signal.aborted) {
    try {
      const response = await checked(await fetch(`/api/v1/walls/${wall.id}/live`, {
        cache: "no-store",
        headers: { Accept: "text/event-stream", "X-Wall-Capability": wall.capability },
        signal,
      }));
      if (!response.body) throw new Error("Live wall response had no stream");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const snapshot = parseSseBlock(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (snapshot) onSnapshot(snapshot);
          boundary = buffer.indexOf("\n\n");
        }
      }
    } catch (reason) {
      if (signal.aborted) return;
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
  }
}
