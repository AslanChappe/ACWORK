from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.http_client import get_http_client
from app.services.n8n_service import N8nService

router = APIRouter()
settings = get_settings()


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str
    services: dict[str, str]


@router.get("/health", response_model=HealthResponse, tags=["monitoring"])
async def health_check() -> HealthResponse:
    """Liveness + dependency check endpoint."""
    n8n_service = N8nService(get_http_client())
    n8n_ok = await n8n_service.health_check()

    return HealthResponse(
        status="ok",
        env=settings.api_env,
        version="1.0.0",
        services={
            "api": "ok",
            "n8n": "ok" if n8n_ok else "unreachable",
        },
    )


@router.get("/ping", tags=["monitoring"])
async def ping() -> dict[str, str]:
    """Minimal liveness probe (no external deps)."""
    return {"pong": "ok"}
