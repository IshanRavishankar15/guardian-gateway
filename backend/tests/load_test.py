"""Repeatable local gateway load check.

Run inside Compose while the normal backend is healthy:
docker compose --profile test run --rm test-runner python -m tests.load_test
"""

import argparse
import asyncio
import json
import os
import time
import uuid

import httpx
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.dependencies import SessionFactory, redis_client
from app.db.models import AuditLog, Client


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percent / 100) * len(ordered) + 0.999999) - 1))
    return ordered[index]


async def run_load(request_count: int, concurrency: int, base_url: str) -> dict[str, int | float]:
    settings = get_settings()
    admin_headers = {"X-Admin-Token": settings.admin_token}
    marker = uuid.uuid4().hex
    client_id = route_id = policy_id = None
    key_id = None
    raw_key = None
    admin = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=15)
    try:
        response = await admin.post(
            "/admin/clients", headers=admin_headers, json={"name": f"load-client-{marker}"}
        )
        response.raise_for_status()
        client_id = response.json()["id"]
        response = await admin.post(f"/admin/clients/{client_id}/api-keys", headers=admin_headers)
        response.raise_for_status()
        key_data = response.json()
        raw_key = key_data["api_key"]
        key_id = key_data["id"]

        path_prefix = f"/load-{marker}"
        response = await admin.post(
            "/admin/routes",
            headers=admin_headers,
            json={
                "name": f"load-route-{marker}",
                "path_prefix": path_prefix,
                "upstream_base_url": os.environ.get("MOCK_UPSTREAM_URL", "http://mock-upstream:9000"),
                "methods": ["GET"],
                "timeout_seconds": 5,
                "enabled": True,
            },
        )
        response.raise_for_status()
        route_id = response.json()["id"]

        capacity = max(1, request_count // 4)
        response = await admin.post(
            "/admin/rate-limit-policies",
            headers=admin_headers,
            json={
                "name": f"load-policy-{marker}",
                "client_id": client_id,
                "route_id": route_id,
                "capacity": capacity,
                "refill_rate": 0.001,
                "enabled": True,
            },
        )
        response.raise_for_status()
        policy_id = response.json()["id"]

        semaphore = asyncio.Semaphore(concurrency)
        latencies: list[float] = []
        statuses: list[int] = []
        transport_errors = 0

        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=20,
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        ) as client:
            async def request_one() -> None:
                nonlocal transport_errors
                async with semaphore:
                    started = time.perf_counter()
                    try:
                        result = await client.get(
                            f"{path_prefix}/echo", headers={"X-API-Key": raw_key}
                        )
                        latencies.append(time.perf_counter() - started)
                        statuses.append(result.status_code)
                    except httpx.HTTPError:
                        latencies.append(time.perf_counter() - started)
                        transport_errors += 1

            started = time.perf_counter()
            await asyncio.gather(*(request_one() for _ in range(request_count)))
            elapsed = time.perf_counter() - started

        rejected = sum(status == 429 for status in statuses)
        http_errors = sum(status >= 400 and status != 429 for status in statuses)
        return {
            "requests": request_count,
            "completed_responses": len(statuses),
            "throughput_requests_per_second": request_count / elapsed if elapsed else 0.0,
            "http_errors": http_errors,
            "transport_errors": transport_errors,
            "rate_limit_rejections": rejected,
            "latency_p50_ms": percentile(latencies, 50) * 1000,
            "latency_p95_ms": percentile(latencies, 95) * 1000,
            "elapsed_seconds": elapsed,
            "configured_burst_capacity": capacity,
        }
    finally:
        await admin.aclose()
        if policy_id:
            async for key in redis_client.scan_iter(match=f"guardian:rate-limit:{policy_id}:*"):
                await redis_client.delete(key)
            await admin_delete(base_url, f"/admin/rate-limit-policies/{policy_id}", admin_headers)
        if route_id:
            await admin_delete(base_url, f"/admin/routes/{route_id}", admin_headers)
        if client_id:
            async with SessionFactory() as session:
                resource_ids = [value for value in (client_id, key_id, route_id, policy_id) if value]
                await session.execute(delete(AuditLog).where(AuditLog.resource_id.in_(resource_ids)))
                await session.execute(delete(Client).where(Client.id == uuid.UUID(client_id)))
                await session.commit()


async def admin_delete(base_url: str, path: str, headers: dict[str, str]) -> None:
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10) as client:
        await client.delete(path, headers=headers)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a temporary quota and concurrency load against Guardian Gateway.")
    parser.add_argument("--requests", type=int, default=200, help="Total requests (default: 200)")
    parser.add_argument("--concurrency", type=int, default=25, help="Concurrent requests (default: 25)")
    parser.add_argument("--base-url", default="http://backend:8000", help="Admin and gateway API base URL")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")
    print(json.dumps(await run_load(args.requests, args.concurrency, args.base_url), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
