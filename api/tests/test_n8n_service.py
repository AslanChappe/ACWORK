"""Tests du N8nService — appels HTTP mockés, pas de vrai n8n requis."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.n8n_service import N8nService


def _make_service(base_url: str = "http://n8n:5678", api_key: str = "") -> N8nService:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    with patch("app.services.n8n_service.settings") as mock_settings:
        mock_settings.n8n_base_url = base_url
        mock_settings.n8n_api_key = api_key
        service = N8nService(mock_client)
    service.client = mock_client
    service.base_url = base_url.rstrip("/")
    service._headers = {"X-N8N-API-KEY": api_key} if api_key else {}
    return service


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


# ── trigger_webhook ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_webhook_calls_correct_url():
    service = _make_service()
    service.client.request = AsyncMock(return_value=_mock_response({"ok": True}))

    await service.trigger_webhook("mon-workflow", {"data": 1})

    service.client.request.assert_called_once()
    call_kwargs = service.client.request.call_args
    assert "http://n8n:5678/webhook/mon-workflow" in call_kwargs[
        0
    ] or "http://n8n:5678/webhook/mon-workflow" in str(call_kwargs)


@pytest.mark.asyncio
async def test_trigger_webhook_strips_leading_slash():
    service = _make_service()
    service.client.request = AsyncMock(return_value=_mock_response({"ok": True}))

    await service.trigger_webhook("/mon-workflow", {})

    url_called = service.client.request.call_args[0][1]
    assert "/webhook//mon-workflow" not in url_called
    assert "/webhook/mon-workflow" in url_called


@pytest.mark.asyncio
async def test_trigger_webhook_returns_json():
    service = _make_service()
    service.client.request = AsyncMock(
        return_value=_mock_response({"execution_id": "abc123", "status": "ok"})
    )

    result = await service.trigger_webhook("test", {})
    assert result["execution_id"] == "abc123"


@pytest.mark.asyncio
async def test_trigger_webhook_raises_on_http_error():
    service = _make_service()
    error_response = MagicMock()
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Server Error", request=MagicMock(), response=MagicMock()
    )
    service.client.request = AsyncMock(return_value=error_response)

    with pytest.raises(httpx.HTTPStatusError):
        await service.trigger_webhook("failing-webhook", {})


@pytest.mark.asyncio
async def test_trigger_webhook_sends_api_key_header():
    service = _make_service(api_key="my-n8n-key")
    service.client.request = AsyncMock(return_value=_mock_response({}))

    await service.trigger_webhook("test", {})

    call_kwargs = service.client.request.call_args[1]
    assert call_kwargs["headers"]["X-N8N-API-KEY"] == "my-n8n-key"


@pytest.mark.asyncio
async def test_trigger_webhook_no_api_key_no_header():
    service = _make_service(api_key="")
    service.client.request = AsyncMock(return_value=_mock_response({}))

    await service.trigger_webhook("test", {})

    call_kwargs = service.client.request.call_args[1]
    assert "X-N8N-API-KEY" not in call_kwargs.get("headers", {})


# ── trigger_test_webhook ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_test_webhook_uses_webhook_test_path():
    service = _make_service()
    service.client.post = AsyncMock(return_value=_mock_response({"ok": True}))

    await service.trigger_test_webhook("my-flow", {"x": 1})

    url_called = service.client.post.call_args[0][0]
    assert "/webhook-test/my-flow" in url_called


# ── health_check ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_returns_true_when_ok():
    service = _make_service()
    ok_response = MagicMock()
    ok_response.status_code = 200
    service.client.get = AsyncMock(return_value=ok_response)

    result = await service.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_health_check_returns_false_on_error():
    service = _make_service()
    service.client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

    result = await service.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_health_check_returns_false_on_non_200():
    service = _make_service()
    bad_response = MagicMock()
    bad_response.status_code = 503
    service.client.get = AsyncMock(return_value=bad_response)

    result = await service.health_check()
    assert result is False
