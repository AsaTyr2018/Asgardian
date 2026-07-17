# Asgardian

Asgardian is a single-user web application for continuous generative image
exploration, source-faithful image editing, and saved-image animation workflows.
It is designed around a fast visual loop: enter a prompt, generate a controlled
batch of images, iterate promising results, save the ones worth keeping, and use
saved assets as the starting point for further creative work.

The application is intentionally built as a private, self-hosted Kubernetes
application. The browser only talks to the Asgardian API; inference engines,
object storage, and internal services stay behind the backend boundary.

## Core features

- Infinite-feeling image wall with server-side soft stops.
- Prompt-driven text-to-image generation.
- Drag-and-drop image editing with source-size preservation.
- Source-faithful edit mode for iterative transformations.
- Temporary session wall for active exploration.
- Persistent saved wall for selected images.
- Image viewer with prompt, metadata, download, save, delete, and iterate
  actions.
- Optional saved-image-to-video workflow.
- Backend-driven job reconciliation so the browser remains a renderer, not a
  worker.
- Object-storage backed artifact handling for inputs, outputs, thumbnails, and
  generated media.

## Architecture

Asgardian is designed to run as several cooperating workloads in a Kubernetes
namespace:

- Web deployment for the React client.
- API deployment for session state, generation requests, asset APIs, and private
  artifact access.
- Worker deployment for dispatching generation and video jobs to external
  inference engines.
- Reconciler deployment for tracking engine-side job completion and committing
  finished artifacts.
- PostgreSQL stateful workload for application metadata.
- Redis stateful workload for lightweight coordination and live update delivery.
- Kubernetes Secrets and ConfigMaps for runtime configuration.
- Kubernetes Ingress for the private web entrypoint.
- S3-compatible object storage outside the application database for binary
  artifacts.

Inference is provided by an external ComfyUI-compatible engine endpoint. The
engine URL and storage credentials are runtime configuration and are never
embedded in the repository.

## Repository layout

```text
apps/web/             React frontend
src/asgardian/        Python backend, worker, reconciler, domain code
migrations/           Alembic database migrations
workflows/            Versioned ComfyUI API workflow templates
tools/                Model download and image build helpers
deploy/               Kubernetes manifests and Helm chart
tests/                Backend tests
Dockerfile.backend    Backend/worker/reconciler image
Dockerfile.web        Web image
compose.yaml          Local development stack
```

## Configuration

Create a local `.env` from the example file:

```bash
cp .env.example .env
```

Configure values through environment variables, including:

- database URL
- Redis URL
- ComfyUI-compatible engine URL
- S3-compatible endpoint, bucket, region, and credentials
- allowed hosts/origins
- optional engine routing mode

## Engine routing mode

`ASGARDIAN_ENGINE_ROUTING_MODE` controls how Asgardian selects inference
engines.

### `solo`

`solo` is the default mode. Image generation, image editing, and video jobs all
use `ASGARDIAN_COMFY_URL`.

```env
ASGARDIAN_ENGINE_ROUTING_MODE=solo
ASGARDIAN_COMFY_URL=http://comfyui.example.local:8188
```

Use this mode when a single ComfyUI-compatible engine can handle every
capability.

### `split`

`split` mode routes image and video jobs to separate explicit engine endpoints.
This is useful when different machines, GPU profiles, or ComfyUI installations
are optimized for different workloads.

```env
ASGARDIAN_ENGINE_ROUTING_MODE=split
ASGARDIAN_COMFY_IMAGE_URL=http://image-engine.example.local:8188
ASGARDIAN_COMFY_VIDEO_URL=http://video-engine.example.local:8188
```

In split mode, both URLs are required and must point to distinct endpoints.
Jobs are pinned to the selected engine when claimed. Asgardian does not
automatically fall back to another engine if a pinned job fails; this avoids
silently mixing workflows, models, or output characteristics.

## Model choice

The bundled workflows are built around a ComfyUI-compatible setup with two
model families:

- A Qwen image/edit capable checkpoint for text-to-image and source-faithful
  image editing.
- An LTX 2.3 style image-to-video stack for optional saved-image animation.

Qwen image/edit was chosen for the primary image loop because it supports both
prompt-first generation and image-conditioned editing in one workflow family.
That keeps the user interface fluid: dropping an image into the wall changes the
job context, not the whole product mode. It also fits Asgardian's source-faithful
edit goal, where the original image should remain structurally recognizable
while the prompt steers the change.

LTX is used for the optional video path because it can produce native high-frame
rate image-to-video outputs without making frame interpolation part of the core
quality path. Video generation is intentionally treated as a saved-asset action,
not as part of the main exploratory image wall.

The repository does not redistribute model weights. Model files can have their
own licenses, usage restrictions, gated downloads, or commercial terms. Review
each model license before use.

The workflow templates currently reference these filenames:

```text
models/checkpoints/Qwen-Rapid-AIO-NSFW-v23.safetensors
models/checkpoints/ltx2310eros_v1_FP8.safetensors
models/loras/ltx-2.3-22b-distilled-lora-384-1.1.safetensors
models/loras/ltx-2-3-60-fps-buttery-smooth-motion-lora-ltx-2-3-.safetensors
models/text_encoders/gemma_3_12B_it_fp8_e4m3fn.safetensors
models/upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors
```

You can either place compatible files at those paths or adjust the ComfyUI API
workflows to match your local model names.

Known public source locations for the referenced files are listed in
`tools/model-manifest.example.json`. Some files may require account login,
accepted model terms, or a platform token. CivitaiArchive can be useful for
discovering older Civitai-hosted assets, but always verify the original model
license and download terms before use.

## Model downloader

`tools/download-comfy-models.py` downloads model files into a ComfyUI directory
from a JSON manifest.

The example manifest includes known source URLs where available:

```text
tools/model-manifest.example.json
```

Copy it, fill in direct URLs or Hugging Face repo/file entries you are allowed
to use, then run:

```bash
python tools/download-comfy-models.py \
  --manifest tools/model-manifest.example.json \
  --comfy-root /path/to/ComfyUI
```

For gated Hugging Face models, provide a token through the environment:

```bash
HF_TOKEN=... python tools/download-comfy-models.py \
  --manifest tools/model-manifest.example.json \
  --comfy-root /path/to/ComfyUI
```

Use `--dry-run` to preview paths and `--force` to overwrite existing files.

See [`tools/README.md`](tools/README.md) for details about the downloader,
manifest format, and local image build helper.

## Kubernetes deployment

The `deploy/` directory contains plain Kubernetes manifests and a Helm chart.
Use them as environment-specific templates rather than fixed production values.

At deployment time, provide:

- image repositories and tags for your registry
- Kubernetes Secrets for database, object storage, and application runtime
  values
- the ComfyUI-compatible engine endpoint
- object storage endpoint, bucket, region, and credentials
- ingress host and TLS configuration
- storage classes suitable for your cluster
- resource requests and limits appropriate for your nodes

The expected runtime shape is:

```text
Ingress
  -> web
      -> api
          -> PostgreSQL
          -> Redis
          -> object storage
          -> worker / reconciler
              -> ComfyUI-compatible engine
```

Container images are build artifacts for Kubernetes. They are not the
deployment model by themselves.

## Local development

Requirements:

- Python 3.12+
- Node.js 22+
- PostgreSQL
- Redis
- S3-compatible object storage
- a reachable ComfyUI-compatible engine

Install backend dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Install frontend dependencies:

```bash
npm install
```

Start backend services in separate terminals:

```bash
asgardian-api
asgardian-worker
asgardian-reconciler
```

Start the web client:

```bash
npm run dev:web
```

For local development, `compose.yaml` can be used as a convenience stack for
supporting services. It is not intended to replace the Kubernetes deployment
model.

## Tests and checks

```bash
ruff check src tests migrations
pytest -q
npm run test:web
npm run build:web
npm audit --audit-level=high
```

## Image build

The project provides separate image definitions for the backend runtime and web
frontend:

```bash
docker build -f Dockerfile.backend -t asgardian-backend:local .
docker build -f Dockerfile.web -t asgardian-web:local .
```

Build and publish images for the CPU architecture used by your Kubernetes
cluster. Multi-platform or architecture-specific builds can be produced with
Docker Buildx or an equivalent CI builder.

Optional helper scripts are documented in [`tools/README.md`](tools/README.md).
Optional in-cluster build manifests are documented in
[`deploy/build/README.md`](deploy/build/README.md).

## License

Asgardian is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE).

Noncommercial use is permitted under that license. Commercial use requires a
separate written commercial license from the project owner. See
[COMMERCIAL.md](COMMERCIAL.md) for details.
