import pytest
from fastapi.testclient import TestClient

from civitai_api.app import app

from .fake import LOCATION, fake_upstream


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.app.state.upstream = fake_upstream()
        yield c


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_models(client):
    r = client.get("/v1/models", params={"source": "civitai.red", "type": "lora,dora", "base_model": "Illustrious",
                                         "sort": "newest", "period": "all", "limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["next_cursor"] == "63212|1266322|43331"
    m = body["items"][0]
    assert m["url"] == "https://civitai.red/models/257749" and m["type"] == "checkpoint"
    assert set(m["versions"][0]) == {"id", "name", "base_model", "trigger_words", "files", "download_url", "images", "created_at"}


def test_validation(client):
    assert client.get("/v1/models", params={"source": "elsewhere"}).status_code == 422
    assert client.get("/v1/models", params={"limit": 0}).status_code == 422
    assert client.get("/v1/models", params={"sort": "random"}).status_code == 422
    assert client.get("/v1/models/abc").status_code == 422


def test_model_and_version(client):
    m = client.get("/v1/models/257749", params={"source": "civitai.com"}).json()
    assert m["source"] == "civitai.com" and len(m["versions"]) == 3
    v = client.get("/v1/versions/290640").json()
    assert (v["model_id"], v["model_name"], v["model_type"], v["creator"]) == (
        257749, "Pony Diffusion V6 XL", "checkpoint", "PurpleSmartAI")
    assert v["created_at"] == "2024-01-10T00:00:00.000Z"


def test_download(client):
    assert client.get("/v1/versions/290640/download", params={"source": "civitai.red"}).json() == {
        "url": LOCATION, "file_name": "v6.safetensors", "size_bytes": round(6775430.712890625 * 1024)}


def test_errors(client):
    r = client.get("/v1/models/999")
    assert r.status_code == 404 and r.json() == {"detail": "not found"}
    r = client.get("/v1/versions/451/download")
    assert r.status_code == 503 and "network location" in r.json()["detail"]
