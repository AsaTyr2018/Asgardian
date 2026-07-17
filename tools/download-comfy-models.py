#!/usr/bin/env python3
"""Download ComfyUI model files from a JSON manifest.

The script intentionally keeps model sources outside the application code.
Different models may have different licenses, access restrictions, or gated
download requirements. Use the example manifest as a template and fill in the
sources you are allowed to use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelEntry:
    name: str
    path: Path
    url: str | None = None
    hf_repo: str | None = None
    hf_file: str | None = None
    required: bool = True


def load_manifest(path: Path) -> list[ModelEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("models")
    if not isinstance(entries, list):
        raise ValueError("manifest must contain a 'models' array")

    models: list[ModelEntry] = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("each model entry must be an object")
        name = str(raw.get("name") or "").strip()
        target = str(raw.get("path") or "").strip()
        if not name or not target:
            raise ValueError("each model entry needs 'name' and 'path'")
        models.append(
            ModelEntry(
                name=name,
                path=Path(target),
                url=_optional_str(raw.get("url")),
                hf_repo=_optional_str(raw.get("hf_repo")),
                hf_file=_optional_str(raw.get("hf_file")),
                required=bool(raw.get("required", True)),
            )
        )
    return models


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def source_url(entry: ModelEntry) -> str | None:
    if entry.url:
        return entry.url
    if entry.hf_repo and entry.hf_file:
        repo = urllib.parse.quote(entry.hf_repo, safe="")
        filename = "/".join(urllib.parse.quote(part, safe="") for part in entry.hf_file.split("/"))
        return f"https://huggingface.co/{repo}/resolve/main/{filename}?download=true"
    return None


def download(url: str, target: Path, token: str | None, force: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        print(f"skip existing: {target}")
        return

    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url)
    if token and "huggingface.co" in urllib.parse.urlparse(url).netloc:
        request.add_header("Authorization", f"Bearer {token}")

    print(f"download: {target}")
    try:
        with urllib.request.urlopen(request) as response, tmp.open("wb") as handle:
            total = response.headers.get("Content-Length")
            expected = int(total) if total and total.isdigit() else None
            copied = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                copied += len(chunk)
                if expected:
                    percent = copied * 100 / expected
                    print(f"\r  {copied / (1024**2):.1f} MiB / {expected / (1024**2):.1f} MiB ({percent:.1f}%)", end="")
            if expected:
                print()
    except urllib.error.HTTPError as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"HTTP {exc.code} while downloading {url}") from exc
    except urllib.error.URLError as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"failed to download {url}: {exc.reason}") from exc

    tmp.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download ComfyUI models from a manifest")
    parser.add_argument("--manifest", type=Path, default=Path("tools/model-manifest.example.json"))
    parser.add_argument(
        "--comfy-root",
        type=Path,
        required=True,
        help="Path to the ComfyUI root directory. Model paths are resolved below this directory.",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--dry-run", action="store_true", help="print planned downloads without downloading")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    models = load_manifest(args.manifest)
    missing_sources = 0

    for entry in models:
        url = source_url(entry)
        target = args.comfy_root / entry.path
        if not url:
            label = "required" if entry.required else "optional"
            print(f"no source configured ({label}): {entry.name} -> {target}")
            if entry.required and not args.dry_run:
                missing_sources += 1
            continue
        if args.dry_run:
            print(f"would download: {entry.name} -> {target}")
            continue
        download(url, target, token=token, force=args.force)

    if missing_sources:
        print(
            f"\n{missing_sources} required model source(s) are not configured. "
            "Edit the manifest with URLs or Hugging Face repo/file entries you are allowed to use.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
