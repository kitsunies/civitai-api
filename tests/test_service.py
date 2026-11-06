import asyncio

from civitai_api import service

from .fake import MODEL, VERSION, fake_upstream


def test_normalise_real_payload():
    m = service.norm_model(MODEL, "civitai.red")
    assert (m.id, m.type, m.source, m.creator) == (257749, "checkpoint", "civitai.red", "PurpleSmartAI")
    assert m.url == "https://civitai.red/models/257749"
    assert m.tags == ["western art", "base model", "my little pony"]
    assert m.stats.downloads == 1128118 and m.stats.likes == 77134
    assert m.cover == "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/4790674c-e16d-4dc7-b384-af4381fcfa3f/width=450/5706937.jpeg"
    v = m.versions[0]
    assert (v.id, v.base_model, v.trigger_words) == (290640, "Pony", [])
    assert v.download_url == "https://civitai.red/api/download/models/290640"
    assert v.created_at == "2026-04-29T20:17:54.942Z"
    model_file, vae = v.files
    assert model_file.primary and not vae.primary
    assert model_file.size_bytes == round(6775430.712890625 * 1024)
    assert model_file.sha256 == "67ab2fd8ec439a89b3fedb15cc65f54336af163c7eb5e4f2acc98f090a29b0b3"
    assert service.norm_model(MODEL, "civitai.com").versions[0].download_url.startswith("https://civitai.com/")


def test_cover_skips_video_and_resizes():
    m = {"id": 1, "modelVersions": [{"id": 2, "images": [
        {"type": "video", "url": "https://image.civitai.com/k/u1/anim=false,width=720/a.mp4"},
        {"type": "image", "url": "https://image.civitai.com/k/u2/width=1024/b.jpeg"},
    ]}]}
    n = service.norm_model(m, "civitai.com")
    assert n.cover == "https://image.civitai.com/k/u2/width=450/b.jpeg"
    assert n.versions[0].images == ["https://image.civitai.com/k/u2/width=1024/b.jpeg"]
    assert n.type is None and n.creator is None and n.stats.downloads == 0
    assert service.norm_model({"id": 3}, "civitai.com").cover is None


def test_search_maps_params():
    seen = []

    async def go():
        up = fake_upstream(seen)
        page = await service.search(up, q="pony", source="civitai.red", types=["lora", "embedding", "Custom"],
                                    base_models=["Illustrious", "NoobAI"], tag="style", sort="most_downloaded",
                                    period="week", limit=5, cursor="abc|1")
        await up.aclose()
        return page

    page = asyncio.run(go())
    assert page.next_cursor == "63212|1266322|43331" and page.items[0].source == "civitai.red"
    params = seen[0].url.params
    assert seen[0].url.host == "civitai.red"
    assert params.get_list("types") == ["LORA", "TextualInversion", "Custom"]
    assert params.get_list("baseModels") == ["Illustrious", "NoobAI"]
    assert (params["query"], params["tag"], params["sort"], params["period"], params["limit"], params["cursor"]) == (
        "pony", "style", "Most Downloaded", "Week", "5", "abc|1")
    assert "page" not in params


def test_default_source(monkeypatch):
    seen = []
    monkeypatch.setenv("DEFAULT_SOURCE", "civitai.red")

    async def go():
        up = fake_upstream(seen)
        await service.search(up)
        await up.aclose()

    asyncio.run(go())
    assert seen[0].url.host == "civitai.red" and set(seen[0].url.params) == {"limit"}


def test_resize_variants():
    assert service.resize("https://i/k/u/original=true/1.jpeg") == "https://i/k/u/width=450/1.jpeg"
    assert service.resize("https://i/k/u/width=96/1.jpeg") == "https://i/k/u/width=450/1.jpeg"
    assert service.resize("https://i/k/u/1.jpeg") == "https://i/k/u/1.jpeg"
