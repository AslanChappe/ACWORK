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

from celery import Task
from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


# ── Tâche principale ───────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.workers.tasks.run_task",
    max_retries=3,
    default_retry_delay=60,        # 1 min entre chaque retry
    acks_late=True,
    track_started=True,
)
def run_task(self: Task, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Point d'entrée unique pour toutes les tâches.
    Appelé via : run_task.delay(str(task.id), task.task_type, task.payload)

    Le wrapping asyncio.run() crée un event loop isolé par worker —
    compatible avec SQLAlchemy asyncpg et httpx.
    """
    logger.info("task.start", extra={"task_id": task_id, "task_type": task_type})
    try:
        return asyncio.run(_execute_task(task_id, task_type, payload))
    except Exception as exc:
        logger.error("task.error", extra={"task_id": task_id, "error": str(exc)})
        raise self.retry(exc=exc) from exc


# ── Dispatcher async ───────────────────────────────────────

async def _execute_task(task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Ouvre une session DB, met à jour le statut, dispatch selon task_type,
    puis sauvegarde le résultat. Tout en async.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.task_service import TaskService

    async with AsyncSessionLocal() as session:
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


async def _dispatch(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Ajoute tes handlers ici selon le task_type reçu de n8n.
    Chaque handler est une coroutine async qui reçoit le payload et retourne un dict.

    Exemple :
        if task_type == "scraping":
            return await _handle_scraping(payload)
        elif task_type == "report_pdf":
            return await _handle_report_pdf(payload)
    """
    handlers = {
        # "mon_type": _handle_mon_type,
    }

    handler = handlers.get(task_type)
    if handler:
        return await handler(payload)

    # Handler par défaut — remplace par une exception si tu veux rejeter les types inconnus
    logger.warning("task.unknown_type", extra={"task_type": task_type})
    return {"task_type": task_type, "status": "processed", "payload": payload}


# ── Exemples de handlers (à compléter) ────────────────────

# async def _handle_scraping(payload: dict) -> dict:
#     url = payload["url"]
#     async with http_client_ctx() as client:
#         response = await client.get(url)
#     return {"content": response.text[:500]}

# async def _handle_report_pdf(payload: dict) -> dict:
#     # logique de génération PDF
#     return {"file_path": "/reports/output.pdf"}


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
        "schedule": 60.0,    # toutes les 60 secondes
    },
    # Exemple : nettoyage quotidien des tâches terminées
    # "cleanup-old-tasks": {
    #     "task": "app.workers.tasks.cleanup_old_tasks",
    #     "schedule": crontab(hour=3, minute=0),   # 3h du matin
    # },
}
