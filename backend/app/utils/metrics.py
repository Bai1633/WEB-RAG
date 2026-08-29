"""Prometheus metrics: request counters/latency histogram + /metrics exporter.

Labels use the matched route template (e.g. ``/api/knowledge-bases/{kb_id}/chat``)
rather than the raw path so that KB IDs do not create unbounded label cardinality.
"""

from __future__ import annotations

import time

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count and latency for every non-metrics endpoint."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.url.path == "/metrics":
            # Never instrument the exporter itself (feedback loop).
            return await call_next(request)

        method = request.method
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        # The router fills in scope["route"] while handling the request, so the
        # template is available by the time the response comes back.
        route = request.scope.get("route")
        path_template = getattr(route, "path", request.url.path)

        try:
            REQUEST_COUNT.labels(method, path_template, str(response.status_code)).inc()
            REQUEST_LATENCY.labels(method, path_template).observe(elapsed)
        except Exception as e:  # pragma: no cover - metrics must never break serving
            logger.warning("metrics_recording_failed", error=str(e))

        return response
