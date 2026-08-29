"""Request ID, logging, security, and rate-limiting middleware for FastAPI."""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security-related HTTP headers to every response.

    Headers added:
    - X-Content-Type-Options: prevents MIME type sniffing
    - X-Frame-Options: prevents clickjacking
    - X-XSS-Protection: enables browser XSS filter
    - Strict-Transport-Security: enforces HTTPS (prod only)
    - Referrer-Policy: controls referrer information
    - Permissions-Policy: restricts browser features
    """

    def __init__(self, app, is_production: bool = False) -> None:
        super().__init__(app)
        self.is_production = is_production

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )

        if self.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis token bucket.

    Limits requests per IP address. Returns 429 Too Many Requests
    if the rate limit is exceeded. Falls open (allows request) if
    Redis is unavailable.
    """

    EXEMPT_PATHS: set[str] = {"/api/health", "/api/ready", "/metrics", "/"}

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        from app.utils.rate_limit import default_rate_limiter

        # Only honor X-Forwarded-For when running behind a trusted reverse
        # proxy (TRUST_PROXY_HEADERS=true). Otherwise a client could spoof the
        # header to rotate its rate-limit key; use the socket peer instead.
        if settings.trust_proxy_headers:
            client_ip = (
                request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or (request.client.host if request.client else "unknown")
            )
        else:
            client_ip = request.client.host if request.client else "unknown"

        request_id = getattr(request.state, "request_id", "-")
        allowed = await default_rate_limiter.allow(client_ip)

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                path=request.url.path,
                request_id=request_id,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "code": "rate_limit_exceeded",
                    "request_id": request_id,
                },
                headers={"Retry-After": "6"},
            )

        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that ensures every request has a unique X-Request-ID.

    If the client sends X-Request-ID in the request header, it is reused.
    Otherwise, a new UUIDv4 is generated.
    The request ID is stored in request.state.request_id and set in the
    X-Request-ID response header.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        start_time = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every request with structured data.

    Logs method, path, status code, and response time.
    Skips health check endpoints to reduce noise.
    """

    SKIP_PATHS: set[str] = {"/api/health", "/api/ready", "/metrics", "/"}

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start_time = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        if request.url.path not in self.SKIP_PATHS:
            request_id = getattr(request.state, "request_id", "-")
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                query=str(request.query_params) if request.query_params else "",
                status_code=response.status_code,
                elapsed_ms=round(elapsed_ms, 2),
                request_id=request_id,
                client=request.client.host if request.client else "-",
            )

        return response
