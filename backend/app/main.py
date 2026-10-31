from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.gateway import router as gateway_router
from app.api.health import router as health_router
from app.api.metrics import admin_metrics_router, metrics_router
from app.core.dependencies import engine, redis_client
from app.core.config import get_settings
from app.observability.middleware import PrometheusMiddleware


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.http_client = httpx.AsyncClient(follow_redirects=False)
    yield
    await application.state.http_client.aclose()
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(PrometheusMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Token", "X-API-Key"],
    allow_credentials=False,
)
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(admin_metrics_router)
app.include_router(metrics_router)
app.include_router(gateway_router)
