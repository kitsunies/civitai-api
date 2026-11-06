"""Command line: the same queries as the HTTP API, run in-process (no server needed)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from . import __version__, service
from .upstream import SOURCES, Upstream, UpstreamError


def compact(n: int) -> str:
    for unit, size in (("m", 1_000_000), ("k", 1_000)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(n)


def print_page(page: service.Page) -> None:
    for m in page.items:
        base = m.versions[0].base_model if m.versions else "-"
        print(f"{m.id}  {m.type}  {base}  {m.name}  {compact(m.stats.downloads)} downloads  by {m.creator or '-'}")
    if not page.items:
        print("no results")
    if page.next_cursor:
        print(f"-- more: --cursor '{page.next_cursor}'", file=sys.stderr)


def print_version(v: service.Version, indent: str = "") -> None:
    print(f"{indent}{v.id}  {v.name}  {v.base_model or '-'}")
    if v.trigger_words:
        print(f"{indent}  triggers: {', '.join(v.trigger_words)}")
    for f in v.files:
        size = f"{f.size_bytes / 1e6:.0f} MB" if f.size_bytes else "?"
        print(f"{indent}  {'*' if f.primary else ' '} {f.name}  {size}")


def print_model(m: service.Model) -> None:
    print(f"{m.name}\n  {m.url}\n  {m.type}  by {m.creator or '-'}  "
          f"{compact(m.stats.downloads)} downloads  {compact(m.stats.likes)} likes")
    if m.tags:
        print(f"  tags: {', '.join(m.tags)}")
    print("  versions:")
    for v in m.versions:
        print_version(v, "    ")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="civitai", description="Search the Civitai model catalogue.")
    ap.add_argument("--version", action="version", version=__version__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-s", "--source", choices=SOURCES, help="catalogue host (default: DEFAULT_SOURCE or civitai.com)")
    common.add_argument("--json", action="store_true", help="print JSON instead of text")
    sub = ap.add_subparsers(dest="cmd", required=True)

    search = sub.add_parser("search", parents=[common], help="search or browse models")
    search.add_argument("q", nargs="?", default="", help="keywords; omit to browse")
    search.add_argument("-t", "--type", action="append", default=[], help="lora, checkpoint, ... (repeat or comma-separate)")
    search.add_argument("-b", "--base-model", action="append", default=[], help="Illustrious, NoobAI, ... (repeat or comma-separate)")
    search.add_argument("--tag", help="one Civitai tag, e.g. style")
    search.add_argument("--sort", choices=list(service.SORTS))
    search.add_argument("--period", choices=list(service.PERIODS))
    search.add_argument("-n", "--limit", type=int, default=20)
    search.add_argument("--cursor")
    sub.add_parser("model", parents=[common], help="one model with every version").add_argument("id", type=int)
    sub.add_parser("version", parents=[common], help="one model version").add_argument("id", type=int)
    sub.add_parser("download", parents=[common], help="resolve a version's file URL").add_argument("id", type=int)
    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    return ap


async def run(args) -> object:
    up = Upstream()
    try:
        if args.cmd == "search":
            return await service.search(
                up, q=args.q, source=args.source, types=service.split_csv(args.type),
                base_models=service.split_csv(args.base_model), tag=args.tag, sort=args.sort,
                period=args.period, limit=args.limit, cursor=args.cursor,
            )
        if args.cmd == "model":
            return await service.get_model(up, args.id, args.source)
        if args.cmd == "version":
            return await service.get_version(up, args.id, args.source)
        if args.cmd == "download":
            return await service.get_download(up, args.id, args.source)
    finally:
        await up.aclose()
    raise AssertionError(args.cmd)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("civitai_api.app:app", host=args.host, port=args.port, proxy_headers=True)
        return 0
    try:
        result = asyncio.run(run(args))
    except UpstreamError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 1 if e.status >= 500 else 2
    if args.json:
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
    elif args.cmd == "search":
        print_page(result)
    elif args.cmd == "model":
        print_model(result)
    elif args.cmd == "version":
        print(f"{result.model_name or '-'} ({result.model_type or '-'}) by {result.creator or '-'}")
        print_version(result)
    else:
        print(result.url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
