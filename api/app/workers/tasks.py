"""
Celery tasks — unités de travail exécutées par les workers.

Ajouter un nouveau type de tâche :
  1. Créer un handler async  `async def _handle_mon_type(payload) -> dict`
  2. L'ajouter dans le dispatch de `_execute_task()`
  3. C'est tout — pas besoin de modifier l'endpoint ou le modèle.
"""

import asyncio
import uuid
from typing import Any

from app.workers.celery_app import celery_app
from celery import Task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


# ── Tâche principale ───────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.tasks.run_task",
    max_retries=3,
    default_retry_delay=60,  # 1 min entre chaque retry
    acks_late=True,
    track_started=True,
)
def run_task(
    self: Task, task_id: str, task_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """
    Point d'entrée unique pour toutes les tâches.
    Appelé via : run_task.delay(str(task.id), task.task_type, task.payload)

    Le wrapping asyncio.run() crée un event loop isolé par worker —
    compatible avec SQLAlchemy asyncpg et httpx.
    """
    logger.info(
        "task.start", extra={"task_id": task_id, "task_type": task_type}
    )
    try:
        return asyncio.run(_execute_task(task_id, task_type, payload))
    except Exception as exc:
        logger.error(
            "task.error", extra={"task_id": task_id, "error": str(exc)}
        )
        raise self.retry(exc=exc) from exc


# ── Dispatcher async ───────────────────────────────────────


async def _execute_task(
    task_id: str, task_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """
    Ouvre une session DB, met à jour le statut, dispatch selon task_type,
    puis sauvegarde le résultat. Tout en async.

    NullPool est requis ici : asyncio.run() crée un nouvel event loop à chaque
    appel Celery, et les connexions asyncpg sont liées à la loop qui les a créées.
    NullPool désactive le pooling → chaque tâche ouvre/ferme sa propre connexion.
    """
    from app.core.config import get_settings
    from app.services.task_service import TaskService
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    _settings = get_settings()
    _engine = create_async_engine(_settings.database_url, poolclass=NullPool)
    _Session = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with _Session() as session:
            service = TaskService(session)
            try:
                await service.mark_running(uuid.UUID(task_id))

                # ── Dispatch par type ──────────────────────────
                result = await _dispatch(task_type, payload)

                await service.mark_success(uuid.UUID(task_id), result)
                await session.commit()
                logger.info("task.success", extra={"task_id": task_id})
                return result

            except Exception as exc:
                await service.mark_failed(uuid.UUID(task_id), str(exc))
                await session.commit()
                raise
    finally:
        await _engine.dispose()


async def _dispatch(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Ajoute tes handlers ici selon le task_type reçu de n8n.
    Chaque handler est une coroutine async qui reçoit le payload et retourne un dict.
    """
    handlers: dict[str, Any] = {
        "text_analysis": _handle_text_analysis,
        # "scraping":      _handle_scraping,
        # "report_pdf":    _handle_report_pdf,
    }

    handler = handlers.get(task_type)
    if handler:
        return await handler(payload)

    # Type inconnu → log + réponse neutre (change en `raise` si tu veux rejeter)
    logger.warning("task.unknown_type", extra={"task_type": task_type})
    return {"task_type": task_type, "status": "processed", "payload": payload}


# ── Handlers métier ────────────────────────────────────────


async def _handle_text_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Exemple d'aller-retour n8n ↔ FastAPI.
    Reçoit un texte, retourne des statistiques simples.

    Payload attendu : { "text": "..." }
    Résultat        : { "word_count": N, "char_count": N, "sentences": N,
                        "word_frequency": {...}, "preview": "..." }
    """
    text: str = payload.get("text", "")
    if not text:
        raise ValueError("Le champ 'text' est requis dans le payload.")

    words = text.split()
    sentences = [
        s.strip()
        for s in text.replace("!", ".").replace("?", ".").split(".")
        if s.strip()
    ]

    # Fréquence des mots (sans ponctuation, en minuscules)
    import re

    clean_words = [
        re.sub(r"[^\w]", "", w).lower()
        for w in words
        if re.sub(r"[^\w]", "", w)
    ]
    freq: dict[str, int] = {}
    for w in clean_words:
        freq[w] = freq.get(w, 0) + 1
    top_words = dict(
        sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
    )

    return {
        "word_count": len(words),
        "char_count": len(text),
        "sentence_count": len(sentences),
        "word_frequency": top_words,
        "preview": text[:120] + ("…" if len(text) > 120 else ""),
    }


# ── Stubs (à implémenter) ────────────────

# async def _handle_scraping(payload: dict) -> dict:
#     from app.core.http_client import http_client_ctx
#     url = payload["url"]
#     async with http_client_ctx() as client:
#         response = await client.get(url, timeout=15)
#     return {"url": url, "status_code": response.status_code, "preview": response.text[:500]}

# async def _handle_report_pdf(payload: dict) -> dict:
#     # logique de génération PDF (ex: weasyprint, reportlab)
#     return {"file_path": "/reports/output.pdf", "pages": 0}


# ── Tâches planifiées (Celery Beat) ────────────────────────


@celery_app.task(name="app.workers.tasks.heartbeat")
def heartbeat() -> dict[str, str]:
    """
    Tâche de santé — s'exécute toutes les minutes (configurée dans beat_schedule).
    Utile pour vérifier que le worker tourne et pour des métriques.
    """
    logger.info("heartbeat.ok")
    return {"status": "alive"}


# Beat schedule — tâches automatiques récurrentes
# Modifie les intervalles selon tes besoins.
celery_app.conf.beat_schedule = {
    "heartbeat-every-minute": {
        "task": "app.workers.tasks.heartbeat",
        "schedule": 60.0,  # toutes les 60 secondes
    },
    # Exemple : nettoyage quotidien des tâches terminées
    # "cleanup-old-tasks": {
    #     "task": "app.workers.tasks.cleanup_old_tasks",
    #     "schedule": crontab(hour=3, minute=0),   # 3h du matin
    # },
}
