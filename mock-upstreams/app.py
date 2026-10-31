import asyncio

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI(title="Guardian Gateway Mock Upstream")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def echo(path: str, request: Request) -> Response:
    if path == "redirect":
        return Response(status_code=302, headers={"Location": "/target"})

    if path.startswith("large/"):
        try:
            size = min(max(int(path.removeprefix("large/")), 0), 100 * 1024 * 1024)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "size must be an integer"})
        return Response(content=b"x" * size, media_type="application/octet-stream")

    if path.startswith("delay/"):
        try:
            delay = min(max(float(path.removeprefix("delay/")), 0), 30)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "delay must be numeric"})
        await asyncio.sleep(delay)

    if path.startswith("status/"):
        try:
            code = int(path.removeprefix("status/"))
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "status must be an integer"})
        if code < 200 or code > 599:
            return JSONResponse(status_code=400, content={"error": "status must be a final HTTP response code"})
        if code in {204, 304}:
            return Response(status_code=code)
        return JSONResponse(status_code=code, content={"upstream_status": code})

    request_body = await request.body()
    return JSONResponse(
        content={
            "method": request.method,
            "path": f"/{path}" if path else "/",
            "query": request.url.query,
            "headers": dict(request.headers),
            "body": request_body.decode("utf-8", errors="replace"),
        },
        headers={"ETag": '"guardian-mock"', "Cache-Control": "no-store"},
    )
