"""Cached, retrying client for the Civitai REST API (v1).

Outbound requests honour the standard HTTPS_PROXY / NO_PROXY environment
variables (httpx `trust_env`), so no proxy settings live here.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from . import __version__

SOURCES = ("civitai.com", "civitai.red")


class UpstreamError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def default_source() -> str:
    source = os.environ.get("DEFAULT_SOURCE") or "civitai.com"
    if source not in SOURCES:
        raise UpstreamError(f"DEFAULT_SOURCE must be one of {', '.join(SOURCES)}", 500)
    return source


def disposition_filename(url: str) -> str | None:
    """File name from a presigned URL's response-content-disposition parameter."""
    disposition = parse_qs(urlsplit(url).query).get("response-content-disposition", [""])[0]
    rest = disposition.partition("filename=")[2]
    name = rest.split(";")[0].strip().strip('"')
    return name or None


class Upstream:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        ttl: float = float(os.environ.get("CACHE_TTL", 300)),
        max_entries: int = 4096,
        concurrency: int = int(os.environ.get("UPSTREAM_CONCURRENCY", 8)),
        retry_delay: float = 0.5,
    ):
        headers = {"user-agent": f"civitai-api/{__version__}"}
        if key := os.environ.get("CIVITAI_API_KEY"):
            headers["authorization"] = f"Bearer {key}"
        self.http = httpx.AsyncClient(transport=transport, timeout=20, headers=headers, follow_redirects=False)
        self.ttl = ttl
        self.max_entries = max_entries
        self.cache: dict[str, tuple[float, Any]] = {}
        self.gate = asyncio.Semaphore(concurrency)
        self.retry_delay = retry_delay

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _cached(self, key: str, fetch) -> Any:
        hit = self.cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        value = await fetch()
        # ponytail: whole-cache sweep when full, fine for one process; use an LRU if hit rate matters.
        if len(self.cache) >= self.max_entries:
            now = time.monotonic()
            self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
            if len(self.cache) >= self.max_entries:
                self.cache.clear()
        self.cache[key] = (time.monotonic() + self.ttl, value)
        return value

    async def _request(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(3):
            try:
                async with self.gate:
                    r = await self.http.get(url, params=params)
            except httpx.TransportError as e:
                if attempt == 2:
                    raise UpstreamError(f"upstream unreachable: {e}", 504) from e
            else:
                if r.status_code == 451:
                    raise UpstreamError("upstream is not available from this server's network location", 503)
                if r.status_code < 500 and r.status_code != 429:
                    break
                if attempt == 2:
                    raise UpstreamError(f"upstream returned HTTP {r.status_code}", 502)
            await asyncio.sleep(self.retry_delay * 3**attempt)

        if r.status_code == 404:
            raise UpstreamError("not found", 404)
        if r.status_code == 400:
            raise UpstreamError(f"upstream rejected the request: {upstream_message(r)}", 400)
        if r.status_code >= 400:
            raise UpstreamError(f"upstream returned HTTP {r.status_code}: {upstream_message(r)}", 502)
        return r

    async def get(self, source: str, path: str, params: dict | None = None) -> Any:
        """GET https://{source}/api/v1{path}, parsed and cached for `ttl` seconds."""
        url = f"https://{source}/api/v1{path}"

        async def fetch():
            r = await self._request(url, params)
            try:
                return r.json()
            except ValueError as e:
                raise UpstreamError(f"upstream returned non-JSON (HTTP {r.status_code})") from e

        return await self._cached(json.dumps([url, params], sort_keys=True), fetch)

    async def download_location(self, source: str, version_id: int) -> str:
        """The presigned file URL that /api/download/models/{id} redirects to. The file is not fetched."""
        url = f"https://{source}/api/download/models/{version_id}"

        async def fetch():
            r = await self._request(url)
            if not r.is_redirect or "location" not in r.headers:
                raise UpstreamError(f"upstream download did not redirect (HTTP {r.status_code})")
            return r.headers["location"]

        return await self._cached(json.dumps([url]), fetch)

    # Endpoints -----------------------------------------------------------

    async def models(self, source: str, params: dict) -> dict:
        return await self.get(source, "/models", params)

    async def model(self, source: str, model_id: int) -> dict:
        return await self.get(source, f"/models/{model_id}")

    async def version(self, source: str, version_id: int) -> dict:
        return await self.get(source, f"/model-versions/{version_id}")


def upstream_message(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:200] or r.reason_phrase
    if isinstance(body, dict):
        body = body.get("error") or body.get("message") or body
    return str(body)[:200]
