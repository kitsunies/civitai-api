"""Normalised response shapes and the queries behind both the HTTP API and the CLI."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from .upstream import Upstream, UpstreamError, default_source, disposition_filename

SourceOpt = Literal["civitai.com", "civitai.red"]
SortOpt = Literal["most_downloaded", "highest_rated", "newest"]
PeriodOpt = Literal["all", "year", "month", "week", "day"]

SORTS = {"most_downloaded": "Most Downloaded", "highest_rated": "Highest Rated", "newest": "Newest"}
PERIODS = {"all": "AllTime", "year": "Year", "month": "Month", "week": "Week", "day": "Day"}
# Lowercase name -> Civitai ModelType. Unknown values are passed through unchanged.
TYPES = {t.lower(): t for t in (
    "Checkpoint", "TextualInversion", "Hypernetwork", "AestheticGradient", "LORA", "LoCon", "DoRA",
    "Controlnet", "Upscaler", "MotionModule", "VAE", "Poses", "Wildcards", "Workflows", "Detection", "Other",
)} | {"embedding": "TextualInversion"}
COVER_WIDTH = 450


class File(BaseModel):
    name: str
    size_bytes: int | None
    sha256: str | None
    primary: bool


class Version(BaseModel):
    id: int
    name: str
    base_model: str | None
    trigger_words: list[str]
    files: list[File]
    download_url: str
    images: list[str]
    created_at: str | None


class VersionDetail(Version):
    model_id: int | None
    model_name: str | None
    model_type: str | None
    creator: str | None


class Stats(BaseModel):
    downloads: int
    likes: int


class Model(BaseModel):
    id: int
    name: str
    type: str | None
    source: str
    url: str
    creator: str | None
    tags: list[str]
    cover: str | None
    stats: Stats
    versions: list[Version]


class Page(BaseModel):
    items: list[Model]
    next_cursor: str | None


class Download(BaseModel):
    url: str
    file_name: str
    size_bytes: int | None


def split_csv(values: list[str]) -> list[str]:
    return [v.strip() for value in values for v in value.split(",") if v.strip()]


def resize(url: str, width: int = COVER_WIDTH) -> str:
    """Swap the image CDN's transform segment (`width=NNN` or `original=true`) for a fixed width."""
    return re.sub(r"/[^/]*(?:original=true|width=\d+)[^/]*/(?=[^/]+$)", f"/width={width}/", url)


def image_urls(version: dict) -> list[str]:
    """Still images only: video previews are skipped."""
    return [i["url"] for i in version.get("images") or [] if i.get("type", "image") == "image" and i.get("url")]


def norm_file(f: dict) -> File:
    size_kb = f.get("sizeKB")
    sha = (f.get("hashes") or {}).get("SHA256")
    return File(
        name=f.get("name") or "",
        size_bytes=round(size_kb * 1024) if size_kb is not None else None,
        sha256=sha.lower() if sha else None,
        primary=bool(f.get("primary")),
    )


def norm_version(v: dict, source: str) -> Version:
    return Version(
        id=v["id"],
        name=v.get("name") or "",
        base_model=v.get("baseModel"),
        trigger_words=[w.strip() for w in v.get("trainedWords") or [] if w and w.strip()],
        files=[norm_file(f) for f in v.get("files") or []],
        download_url=f"https://{source}/api/download/models/{v['id']}",
        images=image_urls(v),
        created_at=v.get("createdAt") or v.get("publishedAt"),
    )


def norm_model(m: dict, source: str) -> Model:
    versions = m.get("modelVersions") or []
    cover = next((url for v in versions for url in image_urls(v)), None)
    stats = m.get("stats") or {}
    return Model(
        id=m["id"],
        name=m.get("name") or "",
        type=(m.get("type") or "").lower() or None,
        source=source,
        url=f"https://{source}/models/{m['id']}",
        creator=(m.get("creator") or {}).get("username"),
        tags=[t if isinstance(t, str) else t.get("name", "") for t in m.get("tags") or []],
        cover=resize(cover) if cover else None,
        stats=Stats(downloads=stats.get("downloadCount") or 0, likes=stats.get("thumbsUpCount") or 0),
        versions=[norm_version(v, source) for v in versions],
    )


# Queries -----------------------------------------------------------------


async def search(
    up: Upstream,
    q: str = "",
    source: str | None = None,
    types: list[str] = (),
    base_models: list[str] = (),
    tag: str | None = None,
    sort: str | None = None,
    period: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> Page:
    source = source or default_source()
    if not 1 <= limit <= 100:
        raise UpstreamError("limit must be between 1 and 100", 400)
    # Keyword search only pages by cursor upstream, so `page` is never sent.
    params = {"limit": limit, "query": q or None, "tag": tag or None, "cursor": cursor or None,
              "types": [TYPES.get(t.lower(), t) for t in types] or None, "baseModels": list(base_models) or None,
              "sort": SORTS.get(sort or ""), "period": PERIODS.get(period or "")}
    data = await up.models(source, {k: v for k, v in params.items() if v is not None})
    return Page(
        items=[norm_model(m, source) for m in data.get("items") or []],
        next_cursor=(data.get("metadata") or {}).get("nextCursor") or None,
    )


async def get_model(up: Upstream, model_id: int, source: str | None = None) -> Model:
    source = source or default_source()
    return norm_model(await up.model(source, model_id), source)


async def get_version(up: Upstream, version_id: int, source: str | None = None) -> VersionDetail:
    source = source or default_source()
    v = await up.version(source, version_id)
    model = v.get("model") or {}
    creator = None
    if v.get("modelId"):
        # The version payload has no creator: borrow it from the (cached) parent model, best effort.
        try:
            creator = ((await up.model(source, v["modelId"])).get("creator") or {}).get("username")
        except UpstreamError:
            pass
    return VersionDetail(
        **norm_version(v, source).model_dump(),
        model_id=v.get("modelId"),
        model_name=model.get("name"),
        model_type=(model.get("type") or "").lower() or None,
        creator=creator,
    )


async def get_download(up: Upstream, version_id: int, source: str | None = None) -> Download:
    source = source or default_source()
    url = await up.download_location(source, version_id)
    primary = None
    try:
        files = norm_version(await up.version(source, version_id), source).files
        primary = next((f for f in files if f.primary), files[0] if files else None)
    except UpstreamError:
        pass
    return Download(
        url=url,
        file_name=disposition_filename(url) or (primary.name if primary else ""),
        size_bytes=primary.size_bytes if primary else None,
    )
