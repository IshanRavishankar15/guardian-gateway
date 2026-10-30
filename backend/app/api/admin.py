import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import require_admin
from app.core.dependencies import get_session
from app.db.models import APIKey, AuditLog, Client, RateLimitPolicy, Route
from app.schemas.admin import (
    APIKeyCreated, APIKeyRead, ClientCreate, ClientRead, ClientUpdate,
    PolicyCreate, PolicyRead, PolicyUpdate, RouteCreate, RouteRead, RouteUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A resource with a conflicting unique value already exists") from exc


def _audit(session: AsyncSession, action: str, resource_type: str, resource_id: uuid.UUID | None, **details: object) -> None:
    session.add(AuditLog(action=action, resource_type=resource_type, resource_id=str(resource_id) if resource_id else None, details=details))


@router.post("/clients", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def create_client(payload: ClientCreate, session: AsyncSession = Depends(get_session)) -> Client:
    client = Client(name=payload.name)
    session.add(client)
    await session.flush()
    _audit(session, "client.created", "client", client.id)
    await _commit(session)
    await session.refresh(client)
    return client


@router.get("/clients", response_model=list[ClientRead])
async def list_clients(session: AsyncSession = Depends(get_session)) -> list[Client]:
    return list((await session.scalars(select(Client).order_by(Client.created_at.desc()))).all())


@router.patch("/clients/{client_id}", response_model=ClientRead)
async def update_client(client_id: uuid.UUID, payload: ClientUpdate, session: AsyncSession = Depends(get_session)) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    _audit(session, "client.updated", "client", client.id)
    await _commit(session)
    await session.refresh(client)
    return client


@router.post("/clients/{client_id}/api-keys", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(client_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> APIKeyCreated:
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    raw_key = "gg_" + secrets.token_urlsafe(32)
    key = APIKey(client_id=client.id, key_prefix=raw_key[:11], key_hash=hashlib.sha256(raw_key.encode()).hexdigest())
    session.add(key)
    await session.flush()
    _audit(session, "api_key.created", "api_key", key.id, client_id=str(client.id), key_prefix=key.key_prefix)
    await _commit(session)
    await session.refresh(key)
    return APIKeyCreated(id=key.id, client_id=key.client_id, key_prefix=key.key_prefix, api_key=raw_key, created_at=key.created_at)


@router.get("/clients/{client_id}/api-keys", response_model=list[APIKeyRead])
async def list_api_keys(client_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> list[APIKey]:
    if await session.get(Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return list((await session.scalars(select(APIKey).where(APIKey.client_id == client_id).order_by(APIKey.created_at.desc()))).all())


@router.post("/api-keys/{key_id}/revoke", response_model=APIKeyRead)
async def revoke_api_key(key_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> APIKey:
    key = await session.get(APIKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        _audit(session, "api_key.revoked", "api_key", key.id, client_id=str(key.client_id), key_prefix=key.key_prefix)
        await _commit(session)
        await session.refresh(key)
    return key


@router.post("/routes", response_model=RouteRead, status_code=status.HTTP_201_CREATED)
async def create_route(payload: RouteCreate, session: AsyncSession = Depends(get_session)) -> Route:
    route = Route(**payload.model_dump())
    session.add(route)
    await session.flush()
    _audit(session, "route.created", "route", route.id, name=route.name, path_prefix=route.path_prefix)
    await _commit(session)
    await session.refresh(route)
    return route


@router.get("/routes", response_model=list[RouteRead])
async def list_routes(session: AsyncSession = Depends(get_session)) -> list[Route]:
    return list((await session.scalars(select(Route).order_by(Route.created_at.desc()))).all())


@router.patch("/routes/{route_id}", response_model=RouteRead)
async def update_route(route_id: uuid.UUID, payload: RouteUpdate, session: AsyncSession = Depends(get_session)) -> Route:
    route = await session.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(route, field, value)
    _audit(session, "route.updated", "route", route.id, fields=list(payload.model_fields_set))
    await _commit(session)
    await session.refresh(route)
    return route


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    route = await session.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    _audit(session, "route.deleted", "route", route.id, name=route.name)
    await session.delete(route)
    await _commit(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/rate-limit-policies", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
async def create_policy(payload: PolicyCreate, session: AsyncSession = Depends(get_session)) -> RateLimitPolicy:
    if payload.client_id and await session.get(Client, payload.client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if payload.route_id and await session.get(Route, payload.route_id) is None:
        raise HTTPException(status_code=404, detail="Route not found")
    policy = RateLimitPolicy(**payload.model_dump())
    session.add(policy)
    await session.flush()
    _audit(session, "rate_limit_policy.created", "rate_limit_policy", policy.id, name=policy.name)
    await _commit(session)
    await session.refresh(policy)
    return policy


@router.get("/rate-limit-policies", response_model=list[PolicyRead])
async def list_policies(session: AsyncSession = Depends(get_session)) -> list[RateLimitPolicy]:
    return list((await session.scalars(select(RateLimitPolicy).order_by(RateLimitPolicy.created_at.desc()))).all())


@router.patch("/rate-limit-policies/{policy_id}", response_model=PolicyRead)
async def update_policy(policy_id: uuid.UUID, payload: PolicyUpdate, session: AsyncSession = Depends(get_session)) -> RateLimitPolicy:
    policy = await session.get(RateLimitPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Rate-limit policy not found")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("client_id") and await session.get(Client, updates["client_id"]) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if updates.get("route_id") and await session.get(Route, updates["route_id"]) is None:
        raise HTTPException(status_code=404, detail="Route not found")
    for field, value in updates.items():
        setattr(policy, field, value)
    _audit(session, "rate_limit_policy.updated", "rate_limit_policy", policy.id, fields=list(payload.model_fields_set))
    await _commit(session)
    await session.refresh(policy)
    return policy


@router.delete("/rate-limit-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    policy = await session.get(RateLimitPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Rate-limit policy not found")
    _audit(session, "rate_limit_policy.deleted", "rate_limit_policy", policy.id, name=policy.name)
    await session.delete(policy)
    await _commit(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
