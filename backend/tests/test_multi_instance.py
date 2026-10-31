"""Exercise a shared Redis bucket through two independently running containers."""

import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.dependencies import SessionFactory, redis_client
from app.db.models import AuditLog, Client


@pytest.mark.asyncio
async def test_shared_bucket_across_gateway_processes():
    primary_url = os.environ.get("GATEWAY_PRIMARY_URL")
    replica_url = os.environ.get("GATEWAY_REPLICA_URL")
    if not primary_url or not replica_url:
        pytest.skip("Set both gateway URLs to run the Compose multi-process check")

    admin_headers = {"X-Admin-Token": get_settings().admin_token}
    marker = uuid.uuid4().hex
    resource_ids: list[str] = []
    client_id = route_id = policy_id = None
    async with (
        httpx.AsyncClient(base_url=primary_url, timeout=10) as primary,
        httpx.AsyncClient(base_url=replica_url, timeout=10) as replica,
    ):
        try:
            response = await primary.post(
                "/admin/clients", headers=admin_headers, json={"name": f"multi-instance-{marker}"}
            )
            response.raise_for_status()
            client_id = response.json()["id"]
            resource_ids.append(client_id)

            response = await primary.post(
                f"/admin/clients/{client_id}/api-keys", headers=admin_headers
            )
            response.raise_for_status()
            api_key = response.json()["api_key"]
            resource_ids.append(response.json()["id"])

            route_prefix = f"/multi-instance-{marker}"
            response = await primary.post(
                "/admin/routes",
                headers=admin_headers,
                json={
                    "name": f"multi-instance-route-{marker}",
                    "path_prefix": route_prefix,
                    "upstream_base_url": os.environ.get("MOCK_UPSTREAM_URL", "http://mock-upstream:9000"),
                    "methods": ["GET"],
                },
            )
            response.raise_for_status()
            route_id = response.json()["id"]
            resource_ids.append(route_id)

            response = await primary.post(
                "/admin/rate-limit-policies",
                headers=admin_headers,
                json={
                    "name": f"multi-instance-policy-{marker}",
                    "client_id": client_id,
                    "route_id": route_id,
                    "capacity": 8,
                    "refill_rate": 0.001,
                },
            )
            response.raise_for_status()
            policy_id = response.json()["id"]
            resource_ids.append(policy_id)

            async def request(index: int) -> int:
                gateway = primary if index % 2 == 0 else replica
                result = await gateway.get(
                    f"{route_prefix}/echo", headers={"X-API-Key": api_key}
                )
                return result.status_code

            statuses = await asyncio.gather(*(request(index) for index in range(48)))
            assert statuses.count(200) == 8
            assert statuses.count(429) == 40
            assert set(statuses) == {200, 429}
        finally:
            if policy_id:
                async for key in redis_client.scan_iter(match=f"guardian:rate-limit:{policy_id}:*"):
                    await redis_client.delete(key)
            if route_id:
                await primary.delete(f"/admin/routes/{route_id}", headers=admin_headers)
            if client_id:
                async with SessionFactory() as session:
                    await session.execute(
                        delete(AuditLog).where(AuditLog.resource_id.in_(resource_ids))
                    )
                    await session.execute(delete(Client).where(Client.id == uuid.UUID(client_id)))
                    await session.commit()
