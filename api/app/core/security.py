"""
API key authentication — service-to-service.

Toutes les routes /tasks/* exigent le header X-API-Key.
Les routes /health et /ping restent publiques (monitoring).

Usage n8n : ajouter le header dans chaque nœud HTTP Request :
  X-API-Key: <valeur de INTERNAL_API_KEY dans le .env>
"""

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import get_settings

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> None:
    """
    Dependency FastAPI — injecter via router.include_router(dependencies=[Depends(verify_api_key)]).

    Comportement :
    - Si INTERNAL_API_KEY est vide ET dev → auth désactivée (log warning)
    - Si INTERNAL_API_KEY est vide ET prod → 401 (configuration manquante)
    - Si INTERNAL_API_KEY est défini → vérification stricte dans tous les cas
    """
    settings = get_settings()

    if not settings.internal_api_key:
        if settings.is_dev:
            # Dev sans clé configurée — autorisé mais signalé
            import logging

            logging.getLogger("api.security").warning(
                "INTERNAL_API_KEY not set — auth disabled in dev mode"
            )
            return
        # Prod sans clé — mauvaise configuration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API authentication not configured on server",
        )

    if not hmac.compare_digest(api_key or "", settings.internal_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
