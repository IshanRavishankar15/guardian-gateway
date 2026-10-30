from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.dependencies import engine, redis_client
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
