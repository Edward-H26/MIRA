"""Concurrent streaming-endpoint load test for the ASGI chat backend.

Fires N asynchronous streaming requests at a running Memoria instance and
reports time-to-first-token (TTFT), total duration, and payload counts per
stream. Useful for validating that the Uvicorn worker handles many concurrent
streams without thread starvation.

Usage (from the repo root, with a running server on localhost:8000):

    python scripts/load_test_streams.py \\
        --base-url http://localhost:8000 \\
        --session-id <a-session-id-you-own> \\
        --csrf-token <your-csrf-cookie> \\
        --cookies "sessionid=xxx; csrftoken=yyy" \\
        --n 20 \\
        --prompt "Summarize this conversation in two sentences."

The easiest way to get `--cookies` and `--csrf-token` is to open your browser
devtools on a logged-in chat page and copy the ``Cookie`` request header. The
CSRF token is the ``csrftoken`` cookie value.

Requires: ``pip install httpx`` (already an indirect dep of Django via
requests, but not installed by default — ``pip install httpx`` if missing).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

try:
    import httpx
except ImportError:
    print("httpx not installed; run: pip install httpx", file=sys.stderr)
    sys.exit(1)


async def run_one(client: httpx.AsyncClient, url: str, prompt: str, csrf: str, idx: int):
    """Fire one streaming POST request and collect timing + payload stats."""
    start = time.monotonic()
    ttft = None
    payloads = 0
    deltas = 0
    total_content = 0
    first_payload_type = None
    error = None
    try:
        async with client.stream(
            "POST",
            url,
            data={"message": prompt},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payloads += 1
                ptype = payload.get("type")
                if first_payload_type is None and ptype in ("delta", "done"):
                    first_payload_type = ptype
                    ttft = time.monotonic() - start
                if ptype == "delta":
                    deltas += 1
                    total_content += len(payload.get("content") or "")
                if ptype == "done":
                    break
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"

    duration = time.monotonic() - start
    return {
        "idx": idx,
        "ttft": ttft,
        "duration": duration,
        "payloads": payloads,
        "deltas": deltas,
        "content_chars": total_content,
        "error": error,
    }


async def main(args):
    url = f"{args.base_url.rstrip('/')}/chat/c/{args.session_id}/"
    headers = {"Cookie": args.cookies} if args.cookies else {}
    print(f"[load-test] target={url} concurrency={args.n} prompt_len={len(args.prompt)}")
    print(f"[load-test] starting at {time.strftime('%H:%M:%S')}")

    timeout = httpx.Timeout(args.timeout, read=args.timeout, connect=10.0)
    limits = httpx.Limits(max_connections=args.n + 10, max_keepalive_connections=args.n + 10)

    started_at = time.monotonic()
    async with httpx.AsyncClient(headers=headers, timeout=timeout, limits=limits) as client:
        tasks = [
            asyncio.create_task(run_one(client, url, args.prompt, args.csrf_token, i))
            for i in range(args.n)
        ]
        results = await asyncio.gather(*tasks)
    wall = time.monotonic() - started_at

    ok = [r for r in results if r["error"] is None]
    err = [r for r in results if r["error"] is not None]

    print()
    print("=" * 64)
    print(f"wall_clock:   {wall:.2f} s")
    print(f"successful:   {len(ok)}/{args.n}")
    print(f"failed:       {len(err)}")
    if ok:
        ttfts = [r["ttft"] for r in ok if r["ttft"] is not None]
        durations = [r["duration"] for r in ok]
        deltas = [r["deltas"] for r in ok]
        chars = [r["content_chars"] for r in ok]
        if ttfts:
            print(
                f"TTFT  p50={statistics.median(ttfts):.2f}s  "
                f"p95={(sorted(ttfts)[int(0.95 * (len(ttfts) - 1))]):.2f}s  "
                f"max={max(ttfts):.2f}s"
            )
        print(
            f"dur   p50={statistics.median(durations):.2f}s  "
            f"p95={(sorted(durations)[int(0.95 * (len(durations) - 1))]):.2f}s  "
            f"max={max(durations):.2f}s"
        )
        print(f"deltas/stream avg={statistics.mean(deltas):.1f}  max={max(deltas)}")
        print(f"content chars avg={statistics.mean(chars):.0f}  max={max(chars)}")
    if err:
        print("\nerrors:")
        for r in err[:5]:
            print(f"  [{r['idx']}] {r['error']}")
        if len(err) > 5:
            print(f"  ... and {len(err) - 5} more")
    print("=" * 64)


def parse_args():
    p = argparse.ArgumentParser(description="Concurrent streaming load test for Memoria ASGI backend.")
    p.add_argument("--base-url", default="http://localhost:8000", help="Scheme + host + port")
    p.add_argument("--session-id", required=True, help="Target conversation session id")
    p.add_argument("--csrf-token", required=True, help="Value of the csrftoken cookie")
    p.add_argument("--cookies", default="", help="Raw Cookie header (e.g. 'sessionid=...; csrftoken=...')")
    p.add_argument("--n", type=int, default=10, help="Number of concurrent streams")
    p.add_argument("--prompt", default="Briefly explain transformer attention.", help="Prompt to send")
    p.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout (s)")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
