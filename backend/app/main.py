"""FastAPI application entry point with production-grade setup."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, chat, documents, knowledge_bases, stats
from app.config import get_settings
from app.db.database import close_db, init_db
from app.utils.exceptions import AppException
from app.utils.logging import setup_logging
from app.utils.metrics import MetricsMiddleware
from app.utils.middleware import (
    RateLimitMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.utils.redis_client import close_redis

settings = get_settings()
logger = structlog.get_logger()


async def ensure_kb_vector_schemas() -> None:
    """Idempotently sync every existing KB's vector table with the current schema.

    ``create_vector_table`` runs only on KB creation, so knowledge bases created
    before a schema change (e.g. the tsvector/trigram hybrid-retrieval columns)
    would otherwise stay on the old schema — silently degrading those retrieval
    channels forever.  Re-running the idempotent DDL for every KB on startup
    closes that gap.
    """
    from sqlalchemy import select

    from app.core.index_manager import VectorIndexManager
    from app.db.database import get_session_factory
    from app.db.models import KnowledgeBase

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(KnowledgeBase.id, KnowledgeBase.embed_dim)
        )
        kbs = result.all()

    if not kbs:
        return

    manager = VectorIndexManager()
    synced = 0
    for kb_id, embed_dim in kbs:
        try:
            async with factory() as session:
                await manager.create_vector_table(
                    db=session, kb_id=kb_id, embed_dim=embed_dim
                )
            synced += 1
        except Exception as e:
            # One broken table must not block application startup.
            logger.warning(
                "kb_vector_schema_sync_failed", kb_id=str(kb_id), error=str(e)
            )
    logger.info("kb_vector_schemas_synced", total=len(kbs), synced=synced)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan handler: startup and shutdown events."""
    # ===== Startup =====
    setup_logging(settings.log_level)
    logger.info("starting_application", environment=settings.environment)

    # Initialize database
    await init_db()
    logger.info("database_initialized")

    # Bring existing per-KB vector tables up to the current hybrid schema
    try:
        await ensure_kb_vector_schemas()
    except Exception as e:
        logger.warning("kb_vector_schema_sync_skipped", error=str(e))

    # Create upload directory
    os.makedirs(settings.upload_dir, exist_ok=True)
    logger.info("upload_dir_ready", path=settings.upload_dir)

    # Warm up the heavy providers in the BACKGROUND so the first real request is
    # not the one paying for them:
    #   * embedding: first call pays client init + TLS handshake (~20s observed
    #     against DashScope, even though later calls are sub-second).
    #   * reranker:  lazily loads a 2.3GB cross-encoder (~50s on CPU).
    # Without this the very first question looks like a hang: nothing is yielded
    # to the SSE stream until retrieval finishes, so the UI spins silently.
    # Each step is bounded by wait_for, so a slow or broken provider can never
    # block startup — it just logs a warning.
    async def _warmup_providers() -> None:
        loop = asyncio.get_running_loop()

        try:
            from app.core.embedding import get_embedding_provider

            await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: get_embedding_provider().get_embeddings(["warmup"])
                ),
                timeout=60,
            )
            logger.info("embedding_warmed_up")
        except Exception as e:
            logger.warning("embedding_warmup_failed", error=str(e))

        if settings.rerank_enabled:
            try:
                from app.core.reranker import rerank

                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: rerank("warmup", [{"text": "warmup", "score": 0.0}]),
                    ),
                    timeout=180,
                )
                logger.info("reranker_warmed_up")
            except Exception as e:
                logger.warning("reranker_warmup_failed", error=str(e))

    asyncio.create_task(_warmup_providers())

    logger.info(
        "server_started",
        host=settings.server_host,
        port=settings.server_port,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model_name,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model_name,
    )

    yield

    # ===== Shutdown =====
    logger.info("shutting_down")
    await close_redis()
    await close_db()
    logger.info("database_closed")
    logger.info("server_stopped")


def create_app() -> FastAPI:
    """Application factory: create and configure the FastAPI app."""
    app = FastAPI(
        title="AI Knowledge Base Q&A System",
        description="Production-grade RAG-based knowledge base question answering API",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS - whitelist based, no wildcard with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
        expose_headers=["Content-Disposition", "X-Request-ID", "X-Response-Time"],
        max_age=86400,
    )

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)

    # Prometheus request metrics (http_requests_total / http_request_duration_seconds)
    app.add_middleware(MetricsMiddleware)

    # Rate limiting (Redis-based, falls open if Redis is down)
    app.add_middleware(RateLimitMiddleware)

    # Request ID
    app.add_middleware(RequestIDMiddleware)

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Global exception handlers
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "app_exception",
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            request_id=request_id,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code, "request_id": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        errors = exc.errors()
        logger.warning(
            "validation_error",
            errors=errors,
            request_id=request_id,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Request validation failed",
                "code": "validation_error",
                "request_id": request_id,
                "errors": [
                    {"loc": e.get("loc", []), "msg": e.get("msg", "")}
                    for e in errors
                ],
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error(
            "unhandled_exception",
            error=str(exc),
            error_type=type(exc).__name__,
            request_id=request_id,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error",
                "code": "internal_error",
                "request_id": request_id,
            },
        )

    # Register routers
    app.include_router(auth.router)
    app.include_router(knowledge_bases.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(stats.router)

    # Prometheus scrape endpoint (unauthenticated; nginx should restrict access
    # in production if the metrics are not meant to be public).
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())

    # Root and health endpoints
    @app.get("/", tags=["root"])
    async def root() -> dict:
        return {
            "message": "AI Knowledge Base Q&A API",
            "version": "2.0.0",
            "status": "running",
        }

    @app.get("/api/health", tags=["health"])
    async def health_check() -> dict:
        """Liveness probe."""
        return {"status": "healthy"}

    @app.get("/api/ready", tags=["health"])
    async def readiness_check() -> dict:
        """Readiness probe: checks DB, Redis, and LLM connectivity."""
        checks: dict[str, str] = {}
        ready = True

        # DB check
        try:
            from sqlalchemy import text

            from app.db.database import get_engine

            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"
            ready = False

        # Redis check
        try:
            from app.utils.redis_client import get_redis

            redis = get_redis()
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"
            ready = False

        return {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.is_development,
    )
