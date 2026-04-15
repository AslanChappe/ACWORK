"""Tests du middleware d'authentification X-API-Key."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import verify_api_key


def _settings(internal_api_key: str = "", is_dev: bool = False) -> MagicMock:
    mock = MagicMock()
    mock.internal_api_key = internal_api_key
    mock.is_dev = is_dev
    return mock


# ── Clé correcte ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correct_key_passes():
    """Une clé valide ne lève pas d'exception."""
    with patch("app.core.security.get_settings", return_value=_settings("secret-key")):
        await verify_api_key("secret-key")  # Pas d'exception


@pytest.mark.asyncio
async def test_wrong_key_raises_401():
    """Une mauvaise clé lève HTTPException 401."""
    with (
        patch("app.core.security.get_settings", return_value=_settings("secret-key")),
        pytest.raises(HTTPException) as exc_info,
    ):
        await verify_api_key("wrong-key")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_key_raises_401():
    """Absence de header lève HTTPException 401 quand une clé est configurée."""
    with (
        patch("app.core.security.get_settings", return_value=_settings("secret-key")),
        pytest.raises(HTTPException) as exc_info,
    ):
        await verify_api_key(None)
    assert exc_info.value.status_code == 401


# ── Mode développement ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_mode_no_key_configured_passes():
    """En dev sans clé configurée, l'auth est désactivée silencieusement."""
    with patch("app.core.security.get_settings", return_value=_settings("", is_dev=True)):
        await verify_api_key(None)  # Pas d'exception


@pytest.mark.asyncio
async def test_dev_mode_with_key_configured_still_enforces():
    """En dev, si une clé est configurée, elle est quand même vérifiée."""
    with (
        patch("app.core.security.get_settings", return_value=_settings("dev-key", is_dev=True)),
        pytest.raises(HTTPException),
    ):
        await verify_api_key("wrong-key")


# ── Mode production ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prod_mode_no_key_configured_raises_401():
    """En prod sans clé configurée, l'auth retourne 401 (config serveur manquante)."""
    with (
        patch("app.core.security.get_settings", return_value=_settings("", is_dev=False)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await verify_api_key(None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_prod_mode_correct_key_passes():
    """En prod avec la bonne clé, la requête passe."""
    with patch("app.core.security.get_settings", return_value=_settings("prod-key", is_dev=False)):
        await verify_api_key("prod-key")  # Pas d'exception


# ── Cas limites ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_key_comparison_is_exact():
    """La comparaison est stricte — pas de correspondance partielle."""
    with (
        patch("app.core.security.get_settings", return_value=_settings("secret")),
        pytest.raises(HTTPException),
    ):
        await verify_api_key("secret-extra")


@pytest.mark.asyncio
async def test_key_is_case_sensitive():
    """La clé est sensible à la casse."""
    with (
        patch("app.core.security.get_settings", return_value=_settings("Secret")),
        pytest.raises(HTTPException),
    ):
        await verify_api_key("secret")
