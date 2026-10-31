from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.gateway import router as gateway_router
from app.api.health import router as health_router
from app.core.dependencies import engine, redis_client
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.http_client = httpx.AsyncClient(follow_redirects=False)
    yield
    await application.state.http_client.aclose()
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(gateway_router)
