from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.dependencies import engine, redis_client

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> dict[str, str]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await redis_client.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="A required dependency is unavailable") from exc
    return {"status": "ready", "postgres": "ok", "redis": "ok"}
