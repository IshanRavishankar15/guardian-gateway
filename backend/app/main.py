from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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


def create_app() -> FastAPI:
    application = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
    application.state.settings = get_settings()

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_by_status = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
        }
        message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code_by_status.get(exc.status_code, "http_error"), "message": message}},
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )
    application.add_middleware(PrometheusMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[get_settings().frontend_origin],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        allow_headers=["Content-Type", "X-Admin-Token", "X-API-Key"],
        allow_credentials=False,
    )
    application.include_router(health_router)
    application.include_router(admin_router)
    application.include_router(admin_metrics_router)
    application.include_router(metrics_router)
    application.include_router(gateway_router)
    return application


app = create_app()
