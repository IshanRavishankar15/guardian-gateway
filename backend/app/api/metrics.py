from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.admin_auth import require_admin
from app.observability.metrics import REGISTRY, dashboard_summary


metrics_router = APIRouter(tags=["metrics"])
admin_metrics_router = APIRouter(
    prefix="/admin/metrics",
    tags=["admin", "metrics"],
    dependencies=[Depends(require_admin)],
)


@metrics_router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@admin_metrics_router.get("/summary")
async def metrics_summary() -> dict[str, int | float]:
    return dashboard_summary()
