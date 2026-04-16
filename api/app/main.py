from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.http_client import close_http_client, init_http_client
from app.core.logging import setup_logging

settings = get_settings()
setup_logging()

# ── Sentry ─────────────────────────────────────────────────
if settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.api_env,
        traces_sample_rate=0.1,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        send_default_pii=False,
    )


# ── Lifespan (startup / shutdown) ──────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    await init_http_client()
    yield
    # Shutdown
    await close_http_client()


# ── App factory ────────────────────────────────────────────
app = FastAPI(
    title="n8n Stack API",
    description="FastAPI backend orchestrated by n8n",
    version="1.0.0",
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
    openapi_url="/openapi.json" if settings.is_dev else None,
    lifespan=lifespan,
)

# ── Prometheus /metrics ────────────────────────────────────
Instrumentator(
    should_group_status_codes=True,
    excluded_handlers=["/metrics", "/api/v1/health", "/api/v1/ping"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# ── CORS ───────────────────────────────────────────────────
# Origines autorisées lues depuis ALLOWED_ORIGINS dans .env (séparées par virgule)
# En dev : wildcard "*" — En prod : liste explicite de domaines HTTPS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)


# ── Global exception handler ───────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    from app.core.logging import get_logger

    logger = get_logger("api.exception")
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ── Routers ────────────────────────────────────────────────
app.include_router(v1_router, prefix=settings.api_prefix)
