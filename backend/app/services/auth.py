import hashlib
import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.dependencies import SessionFactory
from app.db.models import APIKey


async def authenticate_api_key(request: Request) -> uuid.UUID:
    raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key")

    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    async with SessionFactory() as session:
        result = await session.execute(
            select(APIKey)
            .options(joinedload(APIKey.client))
            .where(APIKey.key_hash == digest)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None or api_key.revoked_at is not None or not api_key.client.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key")
        return api_key.client_id
