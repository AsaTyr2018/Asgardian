import { CSSProperties, DragEvent, FormEvent, Fragment, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  createVideo,
  createWall,
  deleteSavedAsset,
  Generation,
  GenerationFormat,
  loadAsset,
  loadSavedAsset,
  saveGeneration,
  SavedAsset,
  subscribeWall,
  submitGeneration,
  VideoJob,
  Wall,
} from "./api";

type LastRequest = { prompt: string; source: File | null; format: GenerationFormat; count: number };
type WallView = "main" | "saved";
type ViewerImage = {
  kind: "generation" | "saved";
  id: string;
  url: string;
  downloadUrl: string;
  prompt: string;
  mode: "text_to_image" | "image_edit";
  format: GenerationFormat | null;
  width: number | null;
  height: number | null;
  seed: number;
  createdAt: string;
  generation?: Generation;
  saved?: SavedAsset;
};

const FORMAT_LABELS: Record<GenerationFormat, string> = {
  portrait: "Portrait",
  square: "Square",
  landscape: "Landscape",
};

function imageFrameStyle(width?: number | null, height?: number | null): CSSProperties {
  if (!width || !height) return {};
  return {
    "--image-ratio": `${width} / ${height}`,
    "--image-long-edge": `${Math.max(width, height)}`,
  } as CSSProperties;
}

function orientationClass(width?: number | null, height?: number | null): string {
  if (!width || !height) return "unknown";
  if (height > width) return "portrait";
  if (width > height) return "landscape";
  return "square";
}

export function App() {
  const [wall, setWall] = useState<Wall | null>(null);
  const [view, setView] = useState<WallView>("main");
  const [jobs, setJobs] = useState<Generation[]>([]);
  const [savedAssets, setSavedAssets] = useState<SavedAsset[]>([]);
  const [savedGenerationIds, setSavedGenerationIds] = useState<Set<string>>(new Set());
  const [videos, setVideos] = useState<VideoJob[]>([]);
  const [animateTarget, setAnimateTarget] = useState<SavedAsset | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SavedAsset | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [motionPrompt, setMotionPrompt] = useState("");
  const [videoSubmitting, setVideoSubmitting] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [format, setFormat] = useState<GenerationFormat>("square");
  const [formatOpen, setFormatOpen] = useState(false);
  const [count, setCount] = useState(8);
  const [countOpen, setCountOpen] = useState(false);
  const [source, setSource] = useState<File | null>(null);
  const [sourcePreview, setSourcePreview] = useState<string | null>(null);
  const [lastRequest, setLastRequest] = useState<LastRequest | null>(null);
  const [dragging, setDragging] = useState(false);
  const [zoomImage, setZoomImage] = useState<ViewerImage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const created = useRef(false);
  const dragDepth = useRef(0);

  useEffect(() => {
    if (created.current) return;
    created.current = true;
    createWall().then(setWall).catch((reason) => setError(String(reason)));
  }, []);

  useEffect(() => {
    if (!wall) return;
    const controller = new AbortController();
    void subscribeWall(wall, (snapshot) => {
      setJobs(snapshot.generations);
      setSavedAssets(snapshot.saved_assets);
      setSavedGenerationIds(new Set(snapshot.saved_assets.map((asset) => asset.source_generation_id)));
      setVideos(snapshot.videos);
      const savedIds = new Set(snapshot.saved_assets.map((asset) => asset.id));
      setAnimateTarget((current) => current && savedIds.has(current.id) ? current : null);
      setDeleteTarget((current) => current && savedIds.has(current.id) ? current : null);
    }, controller.signal).catch((reason) => {
      if (!controller.signal.aborted) setError(`Live wall disconnected: ${String(reason)}`);
    });
    return () => {
      controller.abort();
    };
  }, [wall]);

  useEffect(() => {
    if (!zoomImage) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setZoomImage(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [zoomImage]);

  const activeCount = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "running").length,
    [jobs],
  );

  const displayJobs = useMemo(
    () => [...jobs].sort((left, right) => {
      const leftTime = Date.parse(left.completed_at ?? left.created_at);
      const rightTime = Date.parse(right.completed_at ?? right.created_at);
      return rightTime - leftTime || right.id.localeCompare(left.id);
    }),
    [jobs],
  );

  const selectFile = (file: File | null) => {
    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
    setSource(file);
    setSourcePreview(file ? URL.createObjectURL(file) : null);
    if (file) setFormatOpen(false);
  };

  const acceptDroppedFile = (file: File | undefined) => {
    if (!file || !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("Drop a JPEG, PNG, or WebP image.");
      return;
    }
    selectFile(file);
    setLastRequest(null);
    setView("main");
    window.requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>("#prompt")?.focus());
  };

  const dragEnter = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    if (!event.dataTransfer.types.includes("Files")) return;
    dragDepth.current += 1;
    setDragging(true);
  };

  const dragLeave = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  };

  const drop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    acceptDroppedFile(event.dataTransfer.files[0]);
  };

  const promptKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };

  const prepareSource = (blob: Blob, filename: string) => {
    selectFile(new File([blob], filename, { type: blob.type || "image/png" }));
    setView("main");
    window.requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>("#prompt")?.focus());
  };

  const useResult = async (job: Generation) => {
    if (!wall) return;
    setError(null);
    try {
      setPrompt(job.prompt);
      prepareSource(await loadAsset(wall, job), `asgardian-${job.id}.png`);
    } catch (reason) {
      setError(`Could not prepare this image for editing: ${String(reason)}`);
    }
  };

  const useSaved = async (asset: SavedAsset) => {
    setError(null);
    try {
      setPrompt(asset.prompt);
      prepareSource(await loadSavedAsset(asset), `asgardian-saved-${asset.id}.png`);
    } catch (reason) {
      setError(`Could not prepare this saved image for editing: ${String(reason)}`);
    }
  };

  const saveResult = async (job: Generation) => {
    if (!wall || savedGenerationIds.has(job.id)) return;
    setError(null);
    try {
      await saveGeneration(wall, job);
    } catch (reason) {
      setError(`Could not save this image: ${String(reason)}`);
    }
  };

  const runBatch = async (request: LastRequest) => {
    if (!wall || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitGeneration(wall, request.prompt, request.source, request.format, request.count);
      setLastRequest(request);
      selectFile(null);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!prompt.trim()) return;
    await runBatch({ prompt: prompt.trim(), source, format, count });
  };

  const submitVideo = async (event: FormEvent) => {
    event.preventDefault();
    if (!animateTarget || !motionPrompt.trim() || videoSubmitting) return;
    setVideoSubmitting(true);
    setError(null);
    try {
      await createVideo(animateTarget, motionPrompt.trim());
      setAnimateTarget(null);
      setMotionPrompt("");
    } catch (reason) {
      setError(`Could not start video: ${String(reason)}`);
    } finally {
      setVideoSubmitting(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    const target = deleteTarget;
    setDeleting(true);
    setError(null);
    try {
      await deleteSavedAsset(target);
      setSavedAssets((current) => current.filter((asset) => asset.id !== target.id));
      setSavedGenerationIds((current) => {
        const next = new Set(current);
        next.delete(target.source_generation_id);
        return next;
      });
      setVideos((current) => current.filter((video) => video.saved_asset_id !== target.id));
      if (zoomImage?.saved?.id === target.id) setZoomImage(null);
      if (animateTarget?.id === target.id) setAnimateTarget(null);
      setDeleteTarget(null);
    } catch (reason) {
      setError(`Could not delete this image: ${String(reason)}`);
    } finally {
      setDeleting(false);
    }
  };

  const showGeneration = (job: Generation) => {
    if (!job.result_url || !job.download_url) return;
    setZoomImage({
      kind: "generation", id: job.id, url: job.result_url, downloadUrl: job.download_url,
      prompt: job.prompt, mode: job.mode, format: job.generation_format,
      width: job.width ?? null, height: job.height ?? null, seed: job.seed, createdAt: job.created_at, generation: job,
    });
  };

  const showSaved = (asset: SavedAsset) => {
    setZoomImage({
      kind: "saved", id: asset.id, url: asset.asset_url, downloadUrl: asset.download_url || asset.asset_url,
      prompt: asset.prompt, mode: asset.mode, format: asset.generation_format ?? null,
      width: asset.width ?? null, height: asset.height ?? null, seed: asset.seed, createdAt: asset.created_at, saved: asset,
    });
  };

  const iterateViewer = async () => {
    const selected = zoomImage;
    if (!selected) return;
    setZoomImage(null);
    if (selected.generation) await useResult(selected.generation);
    if (selected.saved) await useSaved(selected.saved);
  };

  return (
    <main
      className={`shell ${view === "saved" ? "saved-view" : ""}`}
      onDragEnter={dragEnter}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={dragLeave}
      onDrop={drop}
    >
      <header className="topbar">
        <div className="brand"><span className="brand-mark">A</span><span>ASGARDIAN</span></div>
        <nav className="wall-nav" aria-label="Walls">
          <button className={view === "main" ? "active" : ""} onClick={() => setView("main")}>Main <b>{jobs.length}</b></button>
          <button className={view === "saved" ? "active" : ""} onClick={() => setView("saved")}>Saved <b>{savedAssets.length}</b></button>
        </nav>
        <div className="session-state"><i className={wall ? "online" : ""} />{wall ? "Engine ready" : "Opening…"}</div>
      </header>

      {view === "main" ? (
        <>
          <section className="wall" aria-live="polite">
            {jobs.length === 0 && <div className="empty"><div className="portal" /><span>Prompt below. Eight images per run.</span></div>}
            {displayJobs.map((job) => (
              <article
                className={`tile ${job.status} ${job.thumbnail_url ? "has-image" : ""} ${orientationClass(job.width, job.height)}`}
                key={job.id}
                style={imageFrameStyle(job.width, job.height)}
              >
                {job.thumbnail_url ? <img src={job.thumbnail_url} alt={job.prompt} loading="lazy" decoding="async" onClick={() => showGeneration(job)} /> : <div className="skeleton"><span>{job.status}</span></div>}
                <div className="tile-overlay">
                  {job.status === "succeeded" && <div className="tile-actions">
                    <button type="button" onClick={() => useResult(job)}>Iterate</button>
                    <button type="button" className={savedGenerationIds.has(job.id) ? "saved" : ""} onClick={() => saveResult(job)}>{savedGenerationIds.has(job.id) ? "Saved" : "Save"}</button>
                  </div>}
                  {job.status === "failed" && <em>{job.error_message ?? "Generation failed"}</em>}
                </div>
              </article>
            ))}
          </section>

          {lastRequest && prompt.trim() === lastRequest.prompt && !source && activeCount === 0 && !submitting && (
            <div className="softstop"><span>{lastRequest.count} / {lastRequest.count} · Soft stop</span><button onClick={() => runBatch({ ...lastRequest, count })}>Generate {count} more</button></div>
          )}

          <form className="composer" onSubmit={submit}>
            {sourcePreview && <div className="source-chip"><img src={sourcePreview} alt="Edit source" /><button type="button" onClick={() => selectFile(null)}>×</button></div>}
            <textarea id="prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={promptKeyDown} placeholder={source ? "Tell Asgardian what to change…" : "Describe what should exist…"} rows={1} />
            {!source && <div className="format-picker">
              <button
                type="button"
                className="format-trigger"
                aria-label={`Format: ${FORMAT_LABELS[format]}`}
                aria-expanded={formatOpen}
                aria-haspopup="true"
                onClick={() => setFormatOpen((open) => !open)}
              >
                <span className={`format-shape ${format}`} />
                <span className="format-chevron">⌄</span>
              </button>
              {formatOpen && <div className="format-menu" role="group" aria-label="Generation format">
                {(Object.keys(FORMAT_LABELS) as GenerationFormat[]).map((option) => <button
                  key={option}
                  type="button"
                  className={format === option ? "active" : ""}
                  aria-label={FORMAT_LABELS[option]}
                  aria-pressed={format === option}
                  title={FORMAT_LABELS[option]}
                  onClick={() => { setFormat(option); setFormatOpen(false); }}
                ><span className={`format-shape ${option}`} /></button>)}
              </div>}
            </div>}
            <div className="count-picker">
              <button
                type="button"
                className="count-trigger"
                aria-label={`Images per run: ${count}`}
                aria-expanded={countOpen}
                aria-haspopup="true"
                onClick={() => setCountOpen((open) => !open)}
              >{count}<span>×</span></button>
              {countOpen && <div className="count-menu" role="group" aria-label="Images per run">
                {Array.from({ length: 8 }, (_, index) => index + 1).map((option) => <button
                  key={option}
                  type="button"
                  className={count === option ? "active" : ""}
                  aria-label={`${option} ${option === 1 ? "image" : "images"}`}
                  aria-pressed={count === option}
                  onClick={() => { setCount(option); setCountOpen(false); }}
                >{option}</button>)}
              </div>}
            </div>
            <div className="composer-meta"><span>{source ? "IMAGE EDIT" : "IMAGINE"}</span><span>{activeCount > 0 ? `${activeCount} ACTIVE` : `${count} PER RUN`}</span></div>
            <button className="submit" disabled={!wall || !prompt.trim() || submitting}>{submitting ? "…" : "↑"}</button>
          </form>
        </>
      ) : (
        <section className="wall saved-wall" aria-live="polite">
          {savedAssets.length === 0 && <div className="empty"><span>Saved images appear here.</span></div>}
          {savedAssets.map((asset) => <Fragment key={asset.id}>
            <article
              className={`tile succeeded has-image ${orientationClass(asset.width, asset.height)}`}
              style={imageFrameStyle(asset.width, asset.height)}
            >
              <img src={asset.thumbnail_url || asset.asset_url} alt={asset.prompt} loading="lazy" decoding="async" onClick={() => showSaved(asset)} />
              <div className="tile-overlay"><div className="tile-actions"><button type="button" onClick={() => useSaved(asset)}>Iterate</button><button type="button" onClick={() => { setAnimateTarget(asset); setMotionPrompt(""); }}>Animate</button><button type="button" className="danger" onClick={() => setDeleteTarget(asset)}>Delete</button></div></div>
            </article>
            {videos.filter((video) => video.saved_asset_id === asset.id).map((video) => (
              <article className={`tile video-tile ${video.status}`} key={video.id}>
                {video.video_url ? <video src={video.video_url} controls loop playsInline preload="metadata" /> : <div className="skeleton"><span>{video.status === "running" ? "creating 12s · 60fps" : video.status}</span></div>}
                {video.status === "failed" && <div className="tile-overlay"><em>{video.error_message ?? "Video generation failed"}</em></div>}
                <div className="video-badge">12s · 60 FPS · NATIVE</div>
              </article>
            ))}
          </Fragment>)}
        </section>
      )}

      {animateTarget && <div className="animate-dialog" role="dialog" aria-label="Animate saved image" onClick={() => setAnimateTarget(null)}>
        <form onSubmit={submitVideo} onClick={(event) => event.stopPropagation()}>
          <img src={animateTarget.thumbnail_url || animateTarget.asset_url} alt="Animation source" loading="lazy" decoding="async" />
          <div><span>IMAGE TO VIDEO</span><strong>12 seconds · native 60 FPS</strong></div>
          <textarea autoFocus value={motionPrompt} onChange={(event) => setMotionPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Describe the movement and camera…" rows={3} />
          <div className="animate-actions"><button type="button" onClick={() => setAnimateTarget(null)}>Cancel</button><button type="submit" disabled={!motionPrompt.trim() || videoSubmitting}>{videoSubmitting ? "Starting…" : "Animate"}</button></div>
        </form>
      </div>}

      {deleteTarget && <div className="delete-dialog" role="dialog" aria-label="Delete saved image" onClick={() => { if (!deleting) setDeleteTarget(null); }}>
        <div onClick={(event) => event.stopPropagation()}>
          <img src={deleteTarget.thumbnail_url || deleteTarget.asset_url} alt="Image to delete" loading="lazy" decoding="async" />
          <section><span>DELETE SAVED IMAGE</span><strong>Remove this image permanently?</strong><p>Its generated videos will also be deleted. This cannot be undone.</p></section>
          <div className="delete-actions"><button type="button" disabled={deleting} onClick={() => setDeleteTarget(null)}>Cancel</button><button type="button" className="confirm-delete" disabled={deleting} onClick={confirmDelete}>{deleting ? "Deletingâ€¦" : "Delete permanently"}</button></div>
        </div>
      </div>}

      {dragging && <div className="drop-overlay"><span>Drop to upload</span></div>}
      {zoomImage && <div className="lightbox" role="dialog" aria-label="Image zoom" onClick={() => setZoomImage(null)}>
        <div
          className={`viewer ${orientationClass(zoomImage.width, zoomImage.height)}`}
          style={imageFrameStyle(zoomImage.width, zoomImage.height)}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="viewer-image"><img src={zoomImage.url} alt={zoomImage.prompt} decoding="async" /></div>
          <aside className="viewer-info">
            <div className="viewer-heading"><span>IMAGE INFO</span></div>
            <section><label>Prompt</label><p>{zoomImage.prompt}</p></section>
            <dl>
              <div><dt>Mode</dt><dd>{zoomImage.mode === "image_edit" ? "Image Edit" : "Imagine"}</dd></div>
              <div><dt>Format</dt><dd>{zoomImage.format ? FORMAT_LABELS[zoomImage.format] : "Source format"}</dd></div>
              <div><dt>Resolution</dt><dd>{zoomImage.width && zoomImage.height ? `${zoomImage.width} × ${zoomImage.height}` : "Original"}</dd></div>
              <div><dt>Seed</dt><dd>{zoomImage.seed}</dd></div>
              <div><dt>Created</dt><dd>{new Date(zoomImage.createdAt).toLocaleString()}</dd></div>
            </dl>
            <div className="viewer-actions">
              <button type="button" onClick={() => navigator.clipboard.writeText(zoomImage.prompt).catch(() => undefined)}>Copy prompt</button>
              <a href={zoomImage.downloadUrl} download>Download original</a>
              <button type="button" className="primary" onClick={iterateViewer}>Iterate</button>
              {zoomImage.generation && <button type="button" onClick={() => saveResult(zoomImage.generation!)}>{savedGenerationIds.has(zoomImage.id) ? "Saved" : "Save"}</button>}
              {zoomImage.saved && <button type="button" className="danger" onClick={() => { setDeleteTarget(zoomImage.saved!); setZoomImage(null); }}>Delete</button>}
            </div>
          </aside>
        </div>
        <button type="button" aria-label="Close image zoom" onClick={() => setZoomImage(null)}>×</button>
      </div>}
      {error && <button className="error" onClick={() => setError(null)}>{error}</button>}
    </main>
  );
}
