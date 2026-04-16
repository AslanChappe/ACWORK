"""
Shared async HTTP client — reused across the app lifetime.
Use this to call n8n webhooks or any external service.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

from app.core.config import get_settings

settings = get_settings()

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialised — call init_http_client() first")
    return _client


async def init_http_client() -> None:
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout),
        headers={"User-Agent": "n8n-stack-api/1.0"},
        follow_redirects=True,
    )


async def close_http_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


@asynccontextmanager
async def http_client_ctx() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Context manager — use in tests or one-off scripts."""
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout),
        follow_redirects=True,
    )
    try:
        yield client
    finally:
        await client.aclose()
