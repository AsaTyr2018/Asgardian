# Tools

This directory contains optional helper scripts for local setup, model
preparation, and image builds. None of these scripts should contain credentials
or environment-specific infrastructure details.

## `download-comfy-models.py`

Downloads ComfyUI model files from a JSON manifest into a ComfyUI installation.

Typical usage:

```bash
python tools/download-comfy-models.py \
  --manifest tools/model-manifest.example.json \
  --comfy-root /path/to/ComfyUI
```

Useful flags:

- `--dry-run`: print the planned target paths without downloading files.
- `--force`: overwrite existing files.

For gated Hugging Face models, set one of these environment variables before
running the script:

```bash
export HF_TOKEN=...
```

or:

```bash
export HUGGINGFACE_HUB_TOKEN=...
```

The token is read only at runtime. Do not commit tokens, generated model files,
or personalized manifests containing private links.

## `model-manifest.example.json`

Example model manifest consumed by `download-comfy-models.py`.

Each entry contains:

- `name`: human-readable model description
- `path`: target path below the ComfyUI root
- `url`: direct download URL
- `required`: whether the model is required for the default image workflow

The downloader also supports Hugging Face source fields:

```json
{
  "name": "Example",
  "path": "models/checkpoints/example.safetensors",
  "hf_repo": "owner/repository",
  "hf_file": "path/in/repository/example.safetensors",
  "required": true
}
```

Model weights are not part of this repository. Review every model's own license,
terms, and usage restrictions before downloading or using it.

## `local-build-registry.ps1`

PowerShell helper for building backend and web images with Docker Buildx.

Example local load:

```powershell
.\tools\local-build-registry.ps1 `
  -Repository ghcr.io/example/asgardian `
  -Version 0.4.0 `
  -Platform linux/arm64 `
  -Load
```

Example push:

```powershell
.\tools\local-build-registry.ps1 `
  -Repository ghcr.io/example/asgardian `
  -Version 0.4.0 `
  -Platform linux/arm64 `
  -Push
```

The script creates tags in this form:

```text
<repository>:backend-<version>-arm64
<repository>:web-<version>-arm64
```

If your registry layout uses separate backend and web repositories, build with
explicit `docker buildx build` commands or adapt the script before publishing.

The build context is protected by `.dockerignore`; keep secrets, diagnostics,
generated media, and local artifacts outside build contexts.
