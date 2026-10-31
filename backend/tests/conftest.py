from contextlib import AsyncExitStack
from dataclasses import dataclass, field
import os
import uuid

import httpx
import pytest_asyncio
from sqlalchemy import delete
from uuid import UUID

from app.core.config import get_settings
from app.core.dependencies import SessionFactory, redis_client
from app.db.models import AuditLog, Client, RateLimitPolicy, Route
from app.main import create_app


@pytest_asyncio.fixture
async def gateway_clients():
    """Two independent FastAPI instances use the configured shared PostgreSQL and Redis."""
    first_app = create_app()
    second_app = create_app()
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(first_app.router.lifespan_context(first_app))
        await stack.enter_async_context(second_app.router.lifespan_context(second_app))
        first_client = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=first_app),
                base_url="http://gateway-one.test",
            )
        )
        second_client = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=second_app),
                base_url="http://gateway-two.test",
            )
        )
        yield first_client, second_client


@dataclass
class GatewayFixture:
    first: httpx.AsyncClient
    second: httpx.AsyncClient
    admin_headers: dict[str, str]
    client_id: str
    route_id: str
    route_prefix: str
    api_key: str
    resource_ids: list[str] = field(default_factory=list)
    policy_ids: list[str] = field(default_factory=list)
    key_ids: list[str] = field(default_factory=list)


@pytest_asyncio.fixture
async def gateway(gateway_clients) -> GatewayFixture:
    first, second = gateway_clients
    admin_headers = {"X-Admin-Token": get_settings().admin_token}
    marker = uuid.uuid4().hex
    client_response = await first.post(
        "/admin/clients",
        headers=admin_headers,
        json={"name": f"pytest-client-{marker}"},
    )
    assert client_response.status_code == 201
    client_data = client_response.json()
    client_id = client_data["id"]

    key_response = await first.post(
        f"/admin/clients/{client_id}/api-keys", headers=admin_headers
    )
    assert key_response.status_code == 201
    key_data = key_response.json()

    route_prefix = f"/pytest-{marker}"
    route_response = await first.post(
        "/admin/routes",
        headers=admin_headers,
        json={
            "name": f"pytest-route-{marker}",
            "path_prefix": route_prefix,
            "upstream_base_url": os.environ.get(
                "MOCK_UPSTREAM_URL", "http://mock-upstream:9000"
            ),
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
            "timeout_seconds": 2.0,
            "enabled": True,
        },
    )
    assert route_response.status_code == 201
    route_data = route_response.json()
    fixture = GatewayFixture(
        first=first,
        second=second,
        admin_headers=admin_headers,
        client_id=client_id,
        route_id=route_data["id"],
        route_prefix=route_prefix,
        api_key=key_data["api_key"],
        resource_ids=[client_id, key_data["id"], route_data["id"]],
        key_ids=[key_data["id"]],
    )
    try:
        yield fixture
    finally:
        async with SessionFactory() as session:
            for policy_id in fixture.policy_ids:
                async for key in redis_client.scan_iter(match=f"guardian:rate-limit:{policy_id}:*"):
                    await redis_client.delete(key)
                await session.execute(delete(RateLimitPolicy).where(RateLimitPolicy.id == UUID(policy_id)))
            await session.execute(
                delete(AuditLog).where(AuditLog.resource_id.in_(fixture.resource_ids + fixture.policy_ids))
            )
            await session.execute(delete(Route).where(Route.id == UUID(fixture.route_id)))
            await session.execute(delete(Client).where(Client.id == UUID(fixture.client_id)))
            await session.commit()


async def add_policy(
    gateway: GatewayFixture,
    *,
    capacity: int,
    refill_rate: float,
) -> str:
    response = await gateway.first.post(
        "/admin/rate-limit-policies",
        headers=gateway.admin_headers,
        json={
            "name": f"pytest-policy-{uuid.uuid4().hex}",
            "client_id": gateway.client_id,
            "route_id": gateway.route_id,
            "capacity": capacity,
            "refill_rate": refill_rate,
            "enabled": True,
        },
    )
    assert response.status_code == 201
    policy_id = response.json()["id"]
    gateway.policy_ids.append(policy_id)
    gateway.resource_ids.append(policy_id)
    return policy_id
