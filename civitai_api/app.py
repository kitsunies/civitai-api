"""HTTP API. Interactive docs at /docs, OpenAPI schema at /openapi.json."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from . import __version__, service
from .service import Download, Model, Page, VersionDetail
from .upstream import Upstream, UpstreamError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.upstream = Upstream()
    yield
    await app.state.upstream.aclose()


app = FastAPI(
    title="civitai-api",
    version=__version__,
    description="Cached, normalised JSON over the Civitai model catalogue on civitai.com and civitai.red.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.exception_handler(UpstreamError)
async def upstream_error(_: Request, exc: UpstreamError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


def upstream(request: Request) -> Upstream:
    return request.app.state.upstream


Up = Annotated[Upstream, Depends(upstream)]
Source = Annotated[service.SourceOpt | None, Query(description="Catalogue host; defaults to the server's DEFAULT_SOURCE.")]
Id = Annotated[int, Path(ge=1)]


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/docs")


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@app.get("/v1/models", response_model=Page, summary="Search or browse models")
async def models(
    up: Up,
    source: Source = None,
    q: Annotated[str, Query(description="Keywords. Empty browses the catalogue.")] = "",
    type: Annotated[list[str], Query(description="lora, locon, dora, checkpoint, embedding, ... (repeat or comma-separate)")] = [],
    base_model: Annotated[list[str], Query(description="Civitai base model, e.g. Illustrious, NoobAI (repeat or comma-separate)")] = [],
    tag: Annotated[str | None, Query(description="One Civitai tag, e.g. style")] = None,
    sort: service.SortOpt | None = None,
    period: service.PeriodOpt | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(description="`next_cursor` from the previous page")] = None,
):
    return await service.search(
        up, q=q, source=source, types=service.split_csv(type), base_models=service.split_csv(base_model),
        tag=tag, sort=sort, period=period, limit=limit, cursor=cursor,
    )


@app.get("/v1/models/{model_id}", response_model=Model, summary="One model with every version")
async def model(model_id: Id, up: Up, source: Source = None):
    return await service.get_model(up, model_id, source)


@app.get("/v1/versions/{version_id}", response_model=VersionDetail, summary="One model version")
async def version(version_id: Id, up: Up, source: Source = None):
    return await service.get_version(up, version_id, source)


@app.get("/v1/versions/{version_id}/download", response_model=Download, summary="Resolve a version's file URL")
async def download(version_id: Id, up: Up, source: Source = None):
    return await service.get_download(up, version_id, source)
