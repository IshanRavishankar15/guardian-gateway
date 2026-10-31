from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.metrics import record_request, request_area


class PrometheusMiddleware:
    """Record end-to-end HTTP timings without putting dynamic paths in labels."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500
        recorded = False
        area = request_area(scope.get("path", "/"))
        method = scope.get("method", "OTHER")

        def record_once() -> None:
            nonlocal recorded
            if not recorded:
                record_request(area, method, status_code, perf_counter() - started_at)
                recorded = True

        async def send_with_metrics(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                record_once()

        try:
            await self.app(scope, receive, send_with_metrics)
        except Exception:
            record_once()
            raise
        finally:
            record_once()
