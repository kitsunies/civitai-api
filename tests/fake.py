"""An in-memory stand-in for the Civitai API, served through httpx.MockTransport.

`models_page.json` is a real (trimmed) /api/v1/models?limit=1 response from civitai.red.
"""

import copy
import json
from pathlib import Path

import httpx

from civitai_api.upstream import Upstream

PAGE = json.loads((Path(__file__).parent / "models_page.json").read_text())
MODEL = PAGE["items"][0]
VERSION = MODEL["modelVersions"][0]
LOCATION = ("https://delivery.example.com/models/v6.safetensors?X-Amz-Expires=86400"
            "&response-content-disposition=attachment%3B%20filename%3D%22v6.safetensors%22&X-Amz-Signature=abc")
BLOCKED = 451


def version_payload() -> dict:
    v = copy.deepcopy(VERSION)
    v.update(modelId=MODEL["id"], createdAt="2024-01-10T00:00:00.000Z",
             model={"name": MODEL["name"], "type": MODEL["type"], "poi": False})
    return v


def handler(seen: list[httpx.Request]):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.rstrip("/").endswith(f"/{BLOCKED}"):
            return httpx.Response(451, json={"error": "Access is not available", "code": "REGION_BLOCKED"})
        if path == "/api/v1/models":
            return httpx.Response(200, json=PAGE)
        if path == f"/api/v1/models/{MODEL['id']}":
            return httpx.Response(200, json=MODEL)
        if path == f"/api/v1/model-versions/{VERSION['id']}":
            return httpx.Response(200, json=version_payload())
        if path == f"/api/download/models/{VERSION['id']}":
            return httpx.Response(307, headers={"location": LOCATION})
        return httpx.Response(404, json={"error": "No model with id"})

    return handle


def fake_upstream(seen: list | None = None, **kwargs) -> Upstream:
    return Upstream(transport=httpx.MockTransport(handler(seen if seen is not None else [])), **kwargs)
