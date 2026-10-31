import asyncio

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI(title="Guardian Gateway Mock Upstream")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def echo(path: str, request: Request) -> Response:
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
        if code < 100 or code > 599:
            return JSONResponse(status_code=400, content={"error": "status is outside the HTTP range"})
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
