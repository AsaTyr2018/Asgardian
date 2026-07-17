import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import * as api from "./api";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    cancelGeneration: vi.fn(),
    createVideo: vi.fn(),
    createWall: vi.fn(),
    deleteSavedAsset: vi.fn(),
    heartbeatWall: vi.fn(),
    listGenerations: vi.fn(),
    listSavedAssets: vi.fn(),
    listVideos: vi.fn(),
    loadAsset: vi.fn(),
    loadSavedAsset: vi.fn(),
    pruneQueue: vi.fn(),
    subscribeWall: vi.fn(),
    submitGeneration: vi.fn(),
  };
});

const wall: api.Wall = {
  id: "b529f46c-f1e9-47ce-b9c0-e159a82bcf67",
  capability: "test-capability",
  expires_at: "2026-07-16T00:00:00Z",
};

describe("Asgardian main wall", () => {
  beforeEach(() => {
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:test") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    vi.mocked(api.listVideos).mockResolvedValue([]);
    vi.mocked(api.heartbeatWall).mockResolvedValue();
    vi.mocked(api.subscribeWall).mockImplementation(async (_wall, onSnapshot, signal) => {
      const [generations, savedAssets, videos] = await Promise.all([
        api.listGenerations(wall), api.listSavedAssets(), api.listVideos(),
      ]);
      onSnapshot({ generations, saved_assets: savedAssets, videos });
      await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("opens an ephemeral wall and submits text generation", async () => {
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    vi.mocked(api.submitGeneration).mockResolvedValue();

    render(<App />);

    expect(await screen.findByText("Engine ready")).toBeInTheDocument();
    const prompt = screen.getByPlaceholderText("Describe what should exist…");
    fireEvent.change(prompt, { target: { value: "A copper raven in fog" } });
    fireEvent.keyDown(prompt, { key: "Enter", shiftKey: false });

    await waitFor(() =>
      expect(api.submitGeneration).toHaveBeenCalledWith(wall, "A copper raven in fog", null, "square", 8),
    );
    expect(prompt).toHaveValue("A copper raven in fog");
  });

  it("queues a new prompt while the current image is still running", async () => {
    const running: api.Generation = {
      id: "45fc9401-d3f7-4a5c-a29f-e3f704737a10",
      batch_id: "e342d0a3-4d43-4f0f-a497-e0d6a318faef",
      wall_id: wall.id,
      status: "running",
      mode: "text_to_image",
      generation_format: "square",
      prompt: "Old prompt",
      seed: 17,
      created_at: "2026-07-16T05:00:00Z",
      completed_at: null,
      result_url: null,
      error_message: null,
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([running]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    vi.mocked(api.submitGeneration).mockResolvedValue();

    render(<App />);
    expect(await screen.findByText("1 ACTIVE")).toBeInTheDocument();
    const prompt = screen.getByPlaceholderText("Describe what should exist…");
    fireEvent.change(prompt, { target: { value: "Replacement prompt" } });
    expect(screen.getByRole("button", { name: "↑" })).toBeEnabled();
    fireEvent.keyDown(prompt, { key: "Enter", shiftKey: false });

    await waitFor(() =>
      expect(api.submitGeneration).toHaveBeenCalledWith(wall, "Replacement prompt", null, "square", 8),
    );
    expect(prompt).toHaveValue("Replacement prompt");
  });

  it("cancels a single queued wall job", async () => {
    const queued: api.Generation = {
      id: "queued-job",
      batch_id: null,
      wall_id: wall.id,
      status: "queued",
      mode: "text_to_image",
      generation_format: "square",
      prompt: "Waiting raven",
      seed: 1,
      created_at: "2026-07-16T00:00:00Z",
      completed_at: null,
      result_url: null,
      thumbnail_url: null,
      download_url: null,
      width: null,
      height: null,
      error_message: null,
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([queued]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    vi.mocked(api.cancelGeneration).mockResolvedValue();

    render(<App />);

    await screen.findByText("queued");
    fireEvent.click(screen.getByRole("button", { name: /kill job/i }));

    await waitFor(() => expect(api.cancelGeneration).toHaveBeenCalledWith(wall, queued));
  });

  it("prunes all active wall jobs from the topbar", async () => {
    const running: api.Generation = {
      id: "running-job",
      batch_id: null,
      wall_id: wall.id,
      status: "running",
      mode: "text_to_image",
      generation_format: "square",
      prompt: "Running raven",
      seed: 1,
      created_at: "2026-07-16T00:00:00Z",
      completed_at: null,
      result_url: null,
      thumbnail_url: null,
      download_url: null,
      width: null,
      height: null,
      error_message: null,
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([running]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    vi.mocked(api.pruneQueue).mockResolvedValue(1);

    render(<App />);

    await screen.findByText("running");
    fireEvent.click(screen.getByRole("button", { name: /prune queue/i }));

    await waitFor(() => expect(api.pruneQueue).toHaveBeenCalledWith(wall));
  });

  it("selects a generation format from the three-button dropdown", async () => {
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    vi.mocked(api.submitGeneration).mockResolvedValue();

    render(<App />);
    const trigger = await screen.findByRole("button", { name: "Format: Square" });
    fireEvent.click(trigger);
    expect(screen.getByRole("group", { name: "Generation format" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Portrait" }));
    expect(screen.getByRole("button", { name: "Format: Portrait" })).toBeInTheDocument();

    const prompt = screen.getByPlaceholderText("Describe what should exist…");
    fireEvent.change(prompt, { target: { value: "A vertical golden gate" } });
    fireEvent.keyDown(prompt, { key: "Enter", shiftKey: false });

    await waitFor(() =>
      expect(api.submitGeneration).toHaveBeenCalledWith(wall, "A vertical golden gate", null, "portrait", 8),
    );
  });

  it("selects a smaller image count while keeping eight as the default", async () => {
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    vi.mocked(api.submitGeneration).mockResolvedValue();

    render(<App />);
    const trigger = await screen.findByRole("button", { name: "Images per run: 8" });
    fireEvent.click(trigger);
    expect(screen.getByRole("group", { name: "Images per run" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "3 images" }));
    expect(screen.getByRole("button", { name: "Images per run: 3" })).toBeInTheDocument();

    const prompt = screen.getByPlaceholderText("Describe what should exist…");
    fireEvent.change(prompt, { target: { value: "Three quick variations" } });
    fireEvent.keyDown(prompt, { key: "Enter", shiftKey: false });

    await waitFor(() =>
      expect(api.submitGeneration).toHaveBeenCalledWith(wall, "Three quick variations", null, "square", 3),
    );
  });

  it("accepts an image dropped anywhere without a visible upload control", async () => {
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);

    const { container } = render(<App />);
    await screen.findByText("Engine ready");
    expect(screen.queryByTitle("Add an image")).not.toBeInTheDocument();

    const file = new File(["image"], "source.png", { type: "image/png" });
    const main = container.querySelector("main")!;
    fireEvent.dragEnter(main, { dataTransfer: { types: ["Files"], files: [file] } });
    expect(screen.getByText("Drop to upload")).toBeInTheDocument();
    fireEvent.drop(main, { dataTransfer: { types: ["Files"], files: [file] } });

    expect(await screen.findByAltText("Edit source")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Tell Asgardian what to change…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Format: Square" })).not.toBeInTheDocument();
  });

  it("opens generated images in a zoom dialog", async () => {
    const generation: api.Generation = {
      id: "7604bee7-dfc2-4dad-bab0-124fc9ffabec",
      batch_id: "bb367958-c6a1-4cbd-a5d3-ec60d03e1130",
      wall_id: wall.id,
      status: "succeeded",
      mode: "text_to_image",
      generation_format: "square",
      prompt: "Newest gate",
      seed: 9,
      created_at: "2026-07-15T20:00:00Z",
      completed_at: "2026-07-15T20:01:00Z",
      result_url: "/api/result.png",
      thumbnail_url: "/api/thumbnail.webp",
      download_url: "/api/download.png",
      width: 1024,
      height: 1024,
      error_message: null,
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([generation]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    vi.mocked(api.loadAsset).mockResolvedValue(new Blob(["image"], { type: "image/png" }));

    render(<App />);
    fireEvent.click(await screen.findByAltText("Newest gate"));
    const dialog = screen.getByRole("dialog", { name: "Image zoom" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("Newest gate")).toBeInTheDocument();
    expect(within(dialog).getByText("1024 × 1024")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Download original" })).toHaveAttribute(
      "href",
      "/api/download.png",
    );
    expect(within(dialog).getByRole("button", { name: "Iterate" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Image zoom" })).not.toBeInTheDocument());
  });

  it("reserves wall space for large image-edit results before full image decode", async () => {
    const generation: api.Generation = {
      id: "44cfd358-2d31-4bb3-a33a-b252cfb4421d",
      batch_id: "7b4bb97c-d0db-4fa8-9093-4f3b6384fdd2",
      wall_id: wall.id,
      status: "succeeded",
      mode: "image_edit",
      generation_format: null,
      prompt: "Large source-faithful edit",
      seed: 91,
      created_at: "2026-07-17T18:00:00Z",
      completed_at: "2026-07-17T18:02:00Z",
      result_url: "/api/large-result.png",
      thumbnail_url: "/api/large-thumbnail.webp",
      download_url: "/api/large-download.png",
      width: 3000,
      height: 2400,
      error_message: null,
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([generation]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);

    render(<App />);

    const image = await screen.findByAltText("Large source-faithful edit");
    const tile = image.closest("article");
    expect(tile).toHaveClass("has-image", "landscape");
    expect(tile).toHaveStyle({ "--image-ratio": "3000 / 2400" });
  });

  it("uses a portrait-aware viewer layout for tall generated images", async () => {
    const generation: api.Generation = {
      id: "e7e9dcfb-e335-4f1d-8f36-335f9ea9de02",
      batch_id: "d5cc1bb7-f47e-44bb-a265-8ac9b126f37d",
      wall_id: wall.id,
      status: "succeeded",
      mode: "image_edit",
      generation_format: null,
      prompt: "Tall source-faithful edit",
      seed: 101,
      created_at: "2026-07-17T18:10:00Z",
      completed_at: "2026-07-17T18:12:00Z",
      result_url: "/api/tall-result.png",
      thumbnail_url: "/api/tall-thumbnail.webp",
      download_url: "/api/tall-download.png",
      width: 1400,
      height: 3200,
      error_message: null,
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([generation]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);

    render(<App />);
    fireEvent.click(await screen.findByAltText("Tall source-faithful edit"));

    const viewer = screen.getByRole("dialog", { name: "Image zoom" }).querySelector(".viewer");
    expect(viewer).toHaveClass("portrait");
    expect(viewer).toHaveStyle({ "--image-ratio": "1400 / 3200" });
    expect(screen.getByText("1400 × 3200")).toBeInTheDocument();
  });

  it("opens one passive live subscription without focus polling", async () => {
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);

    render(<App />);
    await screen.findByText("Engine ready");
    await waitFor(() => expect(api.subscribeWall).toHaveBeenCalledTimes(1));

    fireEvent.focus(window);

    expect(api.subscribeWall).toHaveBeenCalledTimes(1);
  });

  it("renders job state delivered by the backend live stream", async () => {
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listSavedAssets).mockResolvedValue([]);
    let pushSnapshot: ((snapshot: api.LiveSnapshot) => void) | undefined;
    vi.mocked(api.subscribeWall).mockImplementation(async (_wall, onSnapshot, signal) => {
      pushSnapshot = onSnapshot;
      onSnapshot({ generations: [], saved_assets: [], videos: [] });
      await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
    });

    render(<App />);
    await screen.findByText("Engine ready");
    await waitFor(() => expect(pushSnapshot).toBeTypeOf("function"));
    const running = { id: "live-job", batch_id: null, wall_id: wall.id, status: "running",
      mode: "text_to_image", generation_format: "square", prompt: "Live", seed: 1,
      created_at: "2026-07-17T12:00:00Z", completed_at: null, result_url: null,
      error_message: null } satisfies api.Generation;
    act(() => pushSnapshot?.({ generations: [running], saved_assets: [], videos: [] }));
    expect(await screen.findByText("1 ACTIVE")).toBeInTheDocument();
  });

  it("shows saved images in the persistent wall", async () => {
    const saved: api.SavedAsset = {
      id: "eae31d71-e440-4785-9c75-9514ecf23fa6",
      source_generation_id: "91555242-e7ea-4749-829d-ad4872f23caa",
      mode: "text_to_image",
      prompt: "A kept gate",
      seed: 42,
      created_at: "2026-07-15T20:00:00Z",
      asset_url: "/api/v1/library/eae31d71-e440-4785-9c75-9514ecf23fa6/asset",
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([saved]);
    vi.mocked(api.loadSavedAsset).mockResolvedValue(new Blob(["image"], { type: "image/png" }));

    render(<App />);

    const savedTab = await screen.findByRole("button", { name: /Saved 1/ });
    fireEvent.click(savedTab);
    expect(await screen.findByAltText("A kept gate")).toBeInTheDocument();
  });

  it("reconciles saved-wall additions without a page refresh", async () => {
    const saved: api.SavedAsset = {
      id: "c9a90277-fe02-45a6-bb8c-f52602e68a45",
      source_generation_id: "0ad1dcdb-ad4d-4114-9fd8-677e59bd6133",
      mode: "text_to_image",
      prompt: "A newly saved gate",
      seed: 81,
      created_at: "2026-07-17T09:00:00Z",
      asset_url: "/api/v1/library/c9a90277-fe02-45a6-bb8c-f52602e68a45/asset",
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    let pushSnapshot: ((snapshot: api.LiveSnapshot) => void) | undefined;
    vi.mocked(api.subscribeWall).mockImplementation(async (_wall, onSnapshot, signal) => {
      pushSnapshot = onSnapshot;
      onSnapshot({ generations: [], saved_assets: [], videos: [] });
      await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
    });

    render(<App />);
    expect(await screen.findByRole("button", { name: /Saved 0/ })).toBeInTheDocument();
    await waitFor(() => expect(pushSnapshot).toBeTypeOf("function"));
    act(() => pushSnapshot?.({ generations: [], saved_assets: [saved], videos: [] }));

    fireEvent.click(await screen.findByRole("button", { name: /Saved 1/ }));
    expect(await screen.findByAltText("A newly saved gate")).toBeInTheDocument();
  });

  it("starts native video generation from a saved image", async () => {
    const saved: api.SavedAsset = {
      id: "eae31d71-e440-4785-9c75-9514ecf23fa6",
      source_generation_id: "91555242-e7ea-4749-829d-ad4872f23caa",
      mode: "text_to_image",
      prompt: "A kept rune",
      seed: 42,
      created_at: "2026-07-15T20:00:00Z",
      asset_url: "/api/v1/library/eae31d71-e440-4785-9c75-9514ecf23fa6/asset",
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([saved]);
    vi.mocked(api.loadSavedAsset).mockResolvedValue(new Blob(["image"], { type: "image/png" }));
    vi.mocked(api.createVideo).mockResolvedValue();

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Saved 1/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Animate" }));
    expect(screen.getByText("12 seconds · native 60 FPS")).toBeInTheDocument();
    const motion = screen.getByPlaceholderText("Describe the movement and camera…");
    fireEvent.change(motion, { target: { value: "The rune slowly rotates" } });
    fireEvent.keyDown(motion, { key: "Enter", shiftKey: false });

    await waitFor(() => expect(api.createVideo).toHaveBeenCalledWith(saved, "The rune slowly rotates"));
  });

  it("deletes a saved image only after irreversible confirmation", async () => {
    const saved: api.SavedAsset = {
      id: "eae31d71-e440-4785-9c75-9514ecf23fa6",
      source_generation_id: "91555242-e7ea-4749-829d-ad4872f23caa",
      mode: "text_to_image",
      prompt: "A temporary keepsake",
      seed: 42,
      created_at: "2026-07-15T20:00:00Z",
      asset_url: "/api/v1/library/eae31d71-e440-4785-9c75-9514ecf23fa6/asset",
    };
    vi.mocked(api.createWall).mockResolvedValue(wall);
    vi.mocked(api.listGenerations).mockResolvedValue([]);
    vi.mocked(api.listSavedAssets).mockResolvedValue([saved]);
    vi.mocked(api.loadSavedAsset).mockResolvedValue(new Blob(["image"], { type: "image/png" }));
    vi.mocked(api.deleteSavedAsset).mockResolvedValue();

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Saved 1/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByRole("dialog", { name: "Delete saved image" })).toBeInTheDocument();
    expect(screen.getByText(/generated videos will also be deleted/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));

    await waitFor(() => expect(api.deleteSavedAsset).toHaveBeenCalledWith(saved));
    expect(await screen.findByText("Saved images appear here.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Saved 0/ })).toBeInTheDocument();
  });
});
