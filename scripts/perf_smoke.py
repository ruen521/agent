from __future__ import annotations

import argparse
import asyncio
import time

import httpx


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


async def _invoke(client: httpx.AsyncClient, url: str, payload: dict, headers: dict) -> None:
    await client.post(f"{url}/agents/invoke", json=payload, headers=headers)


async def run_smoke(base_url: str, api_key: str | None, concurrency: int, total: int) -> None:
    headers = _headers(api_key)
    payload = {"agent": "inventory_copilot", "input": "summary", "session_id": "smoke"}

    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=20) as client:
        tasks = []
        for _ in range(total):
            tasks.append(_invoke(client, base_url, payload, headers))
            if len(tasks) >= concurrency:
                await asyncio.gather(*tasks)
                tasks = []
        if tasks:
            await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start
    print(f"perf_smoke total={total} concurrency={concurrency} elapsed={elapsed:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--total", type=int, default=100)
    args = parser.parse_args()

    asyncio.run(run_smoke(args.base_url, args.api_key or None, args.concurrency, args.total))


if __name__ == "__main__":
    main()
