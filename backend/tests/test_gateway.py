import asyncio
import hashlib
import json
import logging
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.dependencies import SessionFactory
from app.db.models import APIKey
from tests.conftest import add_policy


@pytest.mark.asyncio
async def test_api_key_validation_revocation_and_secret_storage(gateway, caplog):
    caplog.set_level(logging.INFO)
    url = f"{gateway.route_prefix}/echo"

    missing = await gateway.first.get(url)
    invalid = await gateway.first.get(url, headers={"X-API-Key": "not-a-real-key"})
    valid = await gateway.first.get(url, headers={"X-API-Key": gateway.api_key})
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200

    listed = await gateway.first.get(
        f"/admin/clients/{gateway.client_id}/api-keys", headers=gateway.admin_headers
    )
    assert listed.status_code == 200
    key_list = json.dumps(listed.json())
    assert gateway.api_key not in key_list
    assert "key_hash" not in key_list
    async with SessionFactory() as session:
        saved_key = await session.scalar(
            select(APIKey).where(APIKey.id == UUID(gateway.key_ids[0]))
        )
    assert saved_key is not None
    assert saved_key.key_hash == hashlib.sha256(gateway.api_key.encode()).hexdigest()
    assert gateway.api_key not in caplog.text

    second_key_response = await gateway.first.post(
        f"/admin/clients/{gateway.client_id}/api-keys", headers=gateway.admin_headers
    )
    assert second_key_response.status_code == 201
    second_key = second_key_response.json()
    gateway.key_ids.append(second_key["id"])
    gateway.resource_ids.append(second_key["id"])
    deactivated = await gateway.first.patch(
        f"/admin/clients/{gateway.client_id}",
        headers=gateway.admin_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    inactive_client = await gateway.first.get(
        url, headers={"X-API-Key": second_key["api_key"]}
    )
    assert inactive_client.status_code == 401

    await gateway.first.patch(
        f"/admin/clients/{gateway.client_id}",
        headers=gateway.admin_headers,
        json={"is_active": True},
    )
    revoked = await gateway.first.post(
        f"/admin/api-keys/{gateway.key_ids[0]}/revoke", headers=gateway.admin_headers
    )
    assert revoked.status_code == 200
    revoked_request = await gateway.first.get(
        url, headers={"X-API-Key": gateway.api_key}
    )
    assert revoked_request.status_code == 401


@pytest.mark.asyncio
async def test_admin_authorization_and_upstream_validation(gateway):
    no_token = await gateway.first.get("/admin/routes")
    bad_token = await gateway.first.get(
        "/admin/routes", headers={"X-Admin-Token": "incorrect"}
    )
    assert no_token.status_code == 401
    assert bad_token.status_code == 401
    assert no_token.json()["error"]["code"] == "unauthorized"
    invalid_route = await gateway.first.post(
        "/admin/routes",
        headers=gateway.admin_headers,
        json={
            "name": "pytest-invalid-upstream",
            "path_prefix": "/pytest-invalid-upstream",
            "upstream_base_url": "file:///etc/passwd",
            "methods": ["GET"],
        },
    )
    assert invalid_route.status_code == 422
    assert invalid_route.json()["error"]["code"] == "validation_error"
    unapproved_host = await gateway.first.post(
        "/admin/routes",
        headers=gateway.admin_headers,
        json={
            "name": "pytest-unapproved-host",
            "path_prefix": "/pytest-unapproved-host",
            "upstream_base_url": "http://169.254.169.254/latest/meta-data",
            "methods": ["GET"],
        },
    )
    assert unapproved_host.status_code == 422


@pytest.mark.asyncio
async def test_forwarding_preserves_supported_request_data_and_filters_headers(gateway):
    response = await gateway.first.post(
        f"{gateway.route_prefix}/echo?item=one&count=2",
        headers={
            "X-API-Key": gateway.api_key,
            "X-Request-Id": "request-visible-to-upstream",
            "Authorization": "Bearer do-not-forward",
            "Cookie": "session=do-not-forward",
            "X-Admin-Token": "do-not-forward",
        },
        content="gateway-payload",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "POST"
    assert body["path"] == "/echo"
    assert body["query"] == "item=one&count=2"
    assert body["body"] == "gateway-payload"
    headers = {name.lower(): value for name, value in body["headers"].items()}
    assert headers["x-request-id"] == "request-visible-to-upstream"
    assert "x-api-key" not in headers
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert "x-admin-token" not in headers
    assert response.headers["etag"] == '"guardian-mock"'
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_gateway_body_limits_and_redirect_headers(gateway, monkeypatch):
    monkeypatch.setattr(gateway.settings, "max_gateway_body_bytes", 16)
    request_too_large = await gateway.first.post(
        f"{gateway.route_prefix}/echo",
        headers={"X-API-Key": gateway.api_key},
        content=b"x" * 17,
    )
    assert request_too_large.status_code == 413
    assert request_too_large.json()["error"]["code"] == "request_too_large"

    response_too_large = await gateway.first.get(
        f"{gateway.route_prefix}/large/17", headers={"X-API-Key": gateway.api_key}
    )
    assert response_too_large.status_code == 502
    assert response_too_large.json()["error"]["code"] == "upstream_response_too_large"

    redirect = await gateway.first.get(
        f"{gateway.route_prefix}/redirect", headers={"X-API-Key": gateway.api_key}
    )
    assert redirect.status_code == 302
    assert redirect.headers["location"] == "/target"


@pytest.mark.asyncio
async def test_cors_preflight_allows_all_supported_gateway_methods(gateway):
    response = await gateway.first.options(
        f"{gateway.route_prefix}/echo",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "x-api-key",
        },
    )
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


@pytest.mark.asyncio
async def test_upstream_status_method_timeout_and_connection_errors(gateway):
    status_response = await gateway.first.get(
        f"{gateway.route_prefix}/status/503", headers={"X-API-Key": gateway.api_key}
    )
    assert status_response.status_code == 503
    assert status_response.json()["upstream_status"] == 503
    no_content_response = await gateway.first.get(
        f"{gateway.route_prefix}/status/204", headers={"X-API-Key": gateway.api_key}
    )
    assert no_content_response.status_code == 204
    assert not no_content_response.content

    method_update = await gateway.first.patch(
        f"/admin/routes/{gateway.route_id}",
        headers=gateway.admin_headers,
        json={"methods": ["GET"]},
    )
    assert method_update.status_code == 200
    method_response = await gateway.first.put(
        f"{gateway.route_prefix}/echo", headers={"X-API-Key": gateway.api_key}
    )
    assert method_response.status_code == 405
    assert "Allow" in method_response.headers

    timeout_update = await gateway.first.patch(
        f"/admin/routes/{gateway.route_id}",
        headers=gateway.admin_headers,
        json={"timeout_seconds": 0.05},
    )
    assert timeout_update.status_code == 200
    timeout_response = await gateway.first.get(
        f"{gateway.route_prefix}/delay/0.25", headers={"X-API-Key": gateway.api_key}
    )
    assert timeout_response.status_code == 504
    assert timeout_response.json()["error"]["code"] == "upstream_timeout"

    connect_update = await gateway.first.patch(
        f"/admin/routes/{gateway.route_id}",
        headers=gateway.admin_headers,
        json={"upstream_base_url": "http://127.0.0.1:1", "timeout_seconds": 1},
    )
    assert connect_update.status_code == 200
    connect_response = await gateway.first.get(
        f"{gateway.route_prefix}/echo", headers={"X-API-Key": gateway.api_key}
    )
    assert connect_response.status_code == 502
    assert connect_response.json()["error"]["code"] == "upstream_unavailable"


@pytest.mark.asyncio
async def test_rate_limit_headers_and_rejection(gateway):
    await add_policy(gateway, capacity=2, refill_rate=0.001)
    headers = {"X-API-Key": gateway.api_key}
    first = await gateway.first.get(f"{gateway.route_prefix}/echo", headers=headers)
    second = await gateway.first.get(f"{gateway.route_prefix}/echo", headers=headers)
    rejected = await gateway.first.get(f"{gateway.route_prefix}/echo", headers=headers)

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.status_code == 200
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "rate_limit_exceeded"
    assert rejected.headers["X-RateLimit-Limit"] == "2"
    assert rejected.headers["X-RateLimit-Remaining"] == "0"
    assert int(rejected.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_token_bucket_refills_over_time(gateway):
    await add_policy(gateway, capacity=1, refill_rate=10)
    headers = {"X-API-Key": gateway.api_key}
    first = await gateway.first.get(f"{gateway.route_prefix}/echo", headers=headers)
    exhausted = await gateway.first.get(f"{gateway.route_prefix}/echo", headers=headers)
    await asyncio.sleep(0.15)
    refilled = await gateway.first.get(f"{gateway.route_prefix}/echo", headers=headers)

    assert first.status_code == 200
    assert exhausted.status_code == 429
    assert refilled.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_requests_share_bucket_across_two_app_instances(gateway):
    await add_policy(gateway, capacity=8, refill_rate=0.001)
    path = f"{gateway.route_prefix}/echo"

    async def request(index: int):
        client = gateway.first if index % 2 == 0 else gateway.second
        return await client.get(path, headers={"X-API-Key": gateway.api_key})

    responses = await asyncio.gather(*(request(index) for index in range(48)))
    allowed = [response for response in responses if response.status_code == 200]
    rejected = [response for response in responses if response.status_code == 429]
    unexpected = [response.status_code for response in responses if response.status_code not in {200, 429}]
    assert not unexpected
    assert len(allowed) == 8
    assert len(rejected) == 40
    assert all(response.headers["X-RateLimit-Limit"] == "8" for response in responses)
    assert all(int(response.headers["Retry-After"]) >= 1 for response in rejected)


@pytest.mark.asyncio
async def test_redis_failure_fails_closed(gateway, monkeypatch):
    from redis.exceptions import ConnectionError as RedisConnectionError
    from app.services import rate_limiting

    await add_policy(gateway, capacity=5, refill_rate=1)

    async def redis_unavailable(*args, **kwargs):
        raise RedisConnectionError("injected Redis outage")

    monkeypatch.setattr(rate_limiting.redis_client, "eval", redis_unavailable)
    response = await gateway.first.get(
        f"{gateway.route_prefix}/echo", headers={"X-API-Key": gateway.api_key}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rate_limiter_unavailable"


@pytest.mark.asyncio
async def test_metrics_expose_bounded_labels_and_protect_admin_summary(gateway):
    await gateway.first.get(
        f"{gateway.route_prefix}/echo", headers={"X-API-Key": gateway.api_key}
    )
    public_metrics = await gateway.first.get("/metrics")
    unauthorized_summary = await gateway.first.get("/admin/metrics/summary")
    summary = await gateway.first.get(
        "/admin/metrics/summary", headers=gateway.admin_headers
    )
    assert public_metrics.status_code == 200
    assert "guardian_http_requests_total" in public_metrics.text
    assert "guardian_http_request_duration_seconds_bucket" in public_metrics.text
    assert "path=\"" not in public_metrics.text
    assert unauthorized_summary.status_code == 401
    assert summary.status_code == 200
    assert summary.json()["requests_total"] > 0
