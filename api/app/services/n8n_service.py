"""
N8nService — trigger n8n webhooks and query the n8n API.
n8n acts as orchestrator; this service is the bridge from Python → n8n.
"""

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class N8nService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.base_url = settings.n8n_base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if settings.n8n_api_key:
            self._headers["X-N8N-API-KEY"] = settings.n8n_api_key

    # ── Trigger workflows ──────────────────────────────────

    async def trigger_webhook(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        method: str = "POST",
    ) -> dict[str, Any]:
        """
        Call any n8n webhook by its path.
        Example: await n8n.trigger_webhook("my-workflow", {"key": "value"})
        """
        url = f"{self.base_url}/webhook/{path.lstrip('/')}"
        logger.info("n8n.webhook.trigger", url=url, method=method)

        response = await self.client.request(
            method,
            url,
            json=payload,
            headers=self._headers,
        )
        response.raise_for_status()
        return response.json()

    async def trigger_test_webhook(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Trigger a webhook in test/dev mode (n8n must be listening).
        """
        url = f"{self.base_url}/webhook-test/{path.lstrip('/')}"
        logger.info("n8n.webhook.test_trigger", url=url)
        response = await self.client.post(url, json=payload, headers=self._headers)
        response.raise_for_status()
        return response.json()

    # ── n8n REST API ───────────────────────────────────────

    async def get_execution(self, execution_id: str) -> dict[str, Any]:
        """Retrieve a specific execution from n8n."""
        url = f"{self.base_url}/api/v1/executions/{execution_id}"
        response = await self.client.get(url, headers=self._headers)
        response.raise_for_status()
        return response.json()

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List all workflows from n8n."""
        url = f"{self.base_url}/api/v1/workflows"
        response = await self.client.get(url, headers=self._headers)
        response.raise_for_status()
        return response.json().get("data", [])

    async def health_check(self) -> bool:
        """Check if n8n is reachable."""
        try:
            url = f"{self.base_url}/healthz"
            response = await self.client.get(url, timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.warning("n8n.health_check.failed", error=str(e))
            return False
