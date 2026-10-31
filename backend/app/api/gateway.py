from urllib.parse import quote, unquote

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_session
from app.db.models import Route
from app.services.auth import authenticate_api_key
from app.services.routing import select_route

router = APIRouter(tags=["gateway"])
SUPPORTED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
SAFE_REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "if-match",
    "if-modified-since",
    "if-none-match",
    "if-unmodified-since",
    "range",
    "user-agent",
    "x-request-id",
}
SAFE_RESPONSE_HEADERS = {
    "accept-ranges",
    "cache-control",
    "content-disposition",
    "content-range",
    "content-type",
    "etag",
    "expires",
    "last-modified",
    "vary",
}


def _gateway_error(status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}}, headers=headers)


def _build_upstream_url(route: Route, request_path: str) -> str:
    suffix = request_path[len(route.path_prefix):] if route.path_prefix != "/" else request_path
    suffix = suffix.lstrip("/")
    decoded_segments = unquote(suffix).split("/")
    if any(segment in {".", ".."} for segment in decoded_segments) or "\\" in suffix or "\x00" in suffix:
        raise ValueError("Unsafe path")
    encoded_suffix = quote(suffix, safe="/:@!$&'()*+,;=-._~")
    return f"{route.upstream_base_url.rstrip('/')}/{encoded_suffix}" if suffix else route.upstream_base_url.rstrip("/")


async def _forward(request: Request, route: Route, request_path: str) -> Response:
    try:
        url = _build_upstream_url(route, request_path)
    except ValueError:
        return _gateway_error(400, "invalid_path", "The request path is invalid")

    if request.url.query:
        url = f"{url}?{request.url.query}"

    outgoing_headers = {name: value for name, value in request.headers.items() if name.lower() in SAFE_REQUEST_HEADERS}
    body = await request.body()
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        upstream = await client.request(
            method=request.method,
            url=url,
            headers=outgoing_headers,
            content=body if body else None,
            timeout=route.timeout_seconds,
        )
    except httpx.TimeoutException:
        return _gateway_error(504, "upstream_timeout", "The upstream service timed out")
    except httpx.ConnectError:
        return _gateway_error(502, "upstream_unavailable", "The upstream service is unavailable")
    except httpx.RequestError:
        return _gateway_error(502, "upstream_error", "The request to the upstream service failed")

    response_headers = {name: value for name, value in upstream.headers.items() if name.lower() in SAFE_RESPONSE_HEADERS}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


@router.api_route("/{request_path:path}", methods=SUPPORTED_METHODS)
async def gateway_request(
    request_path: str,
    request: Request,
    client_id=Depends(authenticate_api_key),
    session: AsyncSession = Depends(get_session),
) -> Response:
    # Authentication is performed before route lookup to avoid exposing route configuration.
    request.state.client_id = client_id
    incoming_path = f"/{request_path}" if request_path else "/"
    routes = list((await session.scalars(select(Route).where(Route.enabled.is_(True)))).all())
    route = select_route(routes, incoming_path)
    if route is None:
        return _gateway_error(404, "route_not_found", "No configured route matches this request")
    if request.method not in route.methods:
        return _gateway_error(405, "method_not_allowed", "This method is not enabled for the configured route", {"Allow": ", ".join(route.methods)})
    return await _forward(request, route, incoming_path)
