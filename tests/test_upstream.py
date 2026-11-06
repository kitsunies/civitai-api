import asyncio

import httpx
import pytest

from civitai_api.upstream import Upstream, UpstreamError, disposition_filename

from .fake import LOCATION, VERSION, fake_upstream


def run(coro):
    return asyncio.run(coro)


async def call(up: Upstream, coro_fn):
    try:
        return await coro_fn(up)
    finally:
        await up.aclose()


def test_caches_and_sends_key(monkeypatch):
    monkeypatch.setenv("CIVITAI_API_KEY", "secret")
    seen = []

    async def twice(up):
        return [await up.models("civitai.com", {"limit": 1}) for _ in range(2)]

    a, b = run(call(fake_upstream(seen), twice))
    assert a == b and len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer secret"
    assert str(seen[0].url) == "https://civitai.com/api/v1/models?limit=1"


def test_no_key_no_auth_header(monkeypatch):
    monkeypatch.delenv("CIVITAI_API_KEY", raising=False)
    seen = []
    run(call(fake_upstream(seen), lambda up: up.model("civitai.com", 257749)))
    assert "authorization" not in seen[0].headers


def test_download_location_not_followed():
    seen = []
    loc = run(call(fake_upstream(seen), lambda up: up.download_location("civitai.red", VERSION["id"])))
    assert loc == LOCATION and len(seen) == 1
    assert disposition_filename(loc) == "v6.safetensors"
    assert disposition_filename("https://x/y?a=1") is None


@pytest.mark.parametrize("path,status", [(451, 503), (999, 404)])
def test_error_mapping(path, status):
    with pytest.raises(UpstreamError) as e:
        run(call(fake_upstream(), lambda up: up.model("civitai.com", path)))
    assert e.value.status == status


def test_retries_then_502_and_504():
    calls = []

    def flaky(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    up = Upstream(transport=httpx.MockTransport(flaky), retry_delay=0)
    assert run(call(up, lambda up: up.get("civitai.com", "/x"))) == {"ok": 1} and len(calls) == 3

    up = Upstream(transport=httpx.MockTransport(lambda r: httpx.Response(500)), retry_delay=0)
    with pytest.raises(UpstreamError) as e:
        run(call(up, lambda up: up.get("civitai.com", "/x")))
    assert e.value.status == 502

    def down(request):
        raise httpx.ConnectError("refused")

    up = Upstream(transport=httpx.MockTransport(down), retry_delay=0)
    with pytest.raises(UpstreamError) as e:
        run(call(up, lambda up: up.get("civitai.com", "/x")))
    assert e.value.status == 504
