import time
import uuid

from opentelemetry import trace
from shared.observability.logging import get_logger, request_id_var, trace_id_var
from shared.observability.metrics import REGISTRY
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = get_logger("http")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(req_id)

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.trace_id:
            trace_id_var.set(format(ctx.trace_id, "032x"))

        log.info(
            "http_request_started",
            method=request.method,
            path=str(request.url.path),
            query=str(request.url.query) if request.url.query else None,
            client=request.client.host if request.client else None,
        )

        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = time.monotonic() - start
            log.error(
                "http_request_failed",
                method=request.method,
                path=str(request.url.path),
                duration_seconds=round(duration, 3),
                error=str(exc),
            )
            raise
        else:
            duration = time.monotonic() - start
            log.info(
                "http_request_completed",
                method=request.method,
                path=str(request.url.path),
                status_code=response.status_code,
                duration_seconds=round(duration, 3),
            )

            response.headers["X-Request-ID"] = req_id
            if ctx.trace_id:
                response.headers["X-Trace-ID"] = format(ctx.trace_id, "032x")
            return response
