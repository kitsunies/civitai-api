# civitai-api

A small, cached JSON API and CLI over the [Civitai](https://civitai.com) model catalogue.
It wraps the public Civitai REST API (v1) and returns one compact, normalised shape for models,
versions, files and download links.

- **Two hosts, one switch.** `civitai.com` and `civitai.red` both serve the catalogue;
  `civitai.red` serves the full catalogue. Pick one per request with `source=`.
- **Normalised output.** Lowercase model types, trigger words, file sizes in bytes, lowercase
  SHA256 hashes, a 450px cover image and download links built for the host you queried.
- **Download links without proxying.** `/v1/versions/{id}/download` resolves Civitai's redirect
  and returns the short-lived file URL. The file itself never passes through this service.
- **Cached and gentle.** Responses are cached in memory (5 minutes by default), upstream calls
  are retried with backoff and capped by a concurrency limit.

## Quick start

```bash
pip install git+https://github.com/kitsunies/civitai-api
civitai search "watercolor" --type lora --base-model Illustrious
civitai serve              # HTTP API on :8000, docs at /docs
```

Or with Docker:

```bash
docker run -p 8000:8000 -e DEFAULT_SOURCE=civitai.com ghcr.io/kitsunies/civitai-api
```

## CLI

Every command runs in-process with no server, and takes `--json` for machine-readable output
and `-s/--source civitai.com|civitai.red` to pick the host.

```bash
civitai search "ink" --type lora,locon --base-model Illustrious,NoobAI --sort most_downloaded --period month
civitai search --tag style -n 50                 # browse (no keywords)
civitai search "ink" --cursor '<next_cursor>'    # next page
civitai model 257749                             # one model with every version
civitai version 290640                           # one version: base model, trigger words, files
civitai download 290640                          # print the resolved file URL
```

`search` prints one line per model: id, type, base model of the newest version, name, downloads
and creator. The paging hint goes to stderr (`-- more: --cursor '...'`).

Exit codes: `0` ok, `1` upstream failure, `2` not found or bad input.

## HTTP API

Interactive docs: `/docs`. OpenAPI schema: `/openapi.json`.

| Method | Path | Returns |
|---|---|---|
| GET | `/healthz` | `{"ok": true}` |
| GET | `/v1/models` | `{"items": [Model], "next_cursor": str \| null}` |
| GET | `/v1/models/{id}` | `Model` |
| GET | `/v1/versions/{id}` | `Version` plus `model_id`, `model_name`, `model_type`, `creator` |
| GET | `/v1/versions/{id}/download` | `{"url": str, "file_name": str, "size_bytes": int \| null}` |

Every `/v1` endpoint takes `source=civitai.com|civitai.red` (default: `DEFAULT_SOURCE`).

### `/v1/models` parameters

| Param | Values | Default |
|---|---|---|
| `q` | keywords; empty browses | |
| `type` | `lora`, `locon`, `dora`, `checkpoint`, `embedding`, `vae`, `controlnet`, ... | any |
| `base_model` | Civitai base model names, e.g. `Illustrious`, `NoobAI`, `SDXL 1.0` | any |
| `tag` | one Civitai tag, e.g. `style` | |
| `sort` | `most_downloaded`, `highest_rated`, `newest` | Civitai's default |
| `period` | `all`, `year`, `month`, `week`, `day` | `all` |
| `limit` | 1-100 | 20 |
| `cursor` | `next_cursor` from the previous page | |

`type` and `base_model` accept repeats (`type=lora&type=dora`) or commas (`type=lora,dora`).
Paging is by cursor only.

### Shapes

```json
{"id": 123, "name": "Example", "type": "lora", "source": "civitai.com",
 "url": "https://civitai.com/models/123", "creator": "someone", "tags": ["style"],
 "cover": "https://image.civitai.com/.../width=450/....jpeg",
 "stats": {"downloads": 0, "likes": 0},
 "versions": [{"id": 456, "name": "v1.0", "base_model": "Illustrious", "trigger_words": ["..."],
   "files": [{"name": "x.safetensors", "size_bytes": 123, "sha256": "...", "primary": true}],
   "download_url": "https://civitai.com/api/download/models/456",
   "images": ["https://image.civitai.com/..."], "created_at": "2026-01-01T00:00:00.000Z"}]}
```

### Errors

Errors are `{"detail": "..."}`:

| Status | Meaning |
|---|---|
| 400 | Civitai rejected the request (for example a stale cursor) |
| 404 | Model or version not found |
| 422 | Invalid parameter |
| 502 | Civitai returned an error |
| 503 | Civitai is not available from the server's network location (upstream HTTP 451) |
| 504 | Civitai unreachable |

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `CIVITAI_API_KEY` | Sent upstream as `Authorization: Bearer <key>` | unset |
| `DEFAULT_SOURCE` | `civitai.com` or `civitai.red` | `civitai.com` |
| `HTTPS_PROXY` / `NO_PROXY` | Standard proxy variables, honoured for upstream calls | unset |
| `CACHE_TTL` | Cache lifetime in seconds | `300` |
| `UPSTREAM_CONCURRENCY` | Maximum parallel upstream requests | `8` |
| `HOST` / `PORT` | `civitai serve` bind address | `0.0.0.0` / `8000` |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Tests run offline against an `httpx.MockTransport` fake fed by a real, trimmed `/api/v1/models`
response (`tests/models_page.json`).

CI runs the tests on every push and pull request, and on `main` publishes
`ghcr.io/kitsunies/civitai-api` tagged `latest` and the commit SHA.

## License

MIT
