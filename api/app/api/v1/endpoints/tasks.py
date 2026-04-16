"""
Tasks endpoints — CRUD + dispatch vers Celery.

Flux typique :
  1. n8n appelle  POST /tasks/          → tâche créée en DB (status=pending), envoyée à Celery
  2. Celery worker exécute la logique   → status=running puis success/failed
  3. n8n poll      GET /tasks/{id}      → lit le statut et le résultat
  4. (optionnel)   PATCH /tasks/{id}    → n8n peut écrire un résultat externe
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.http_client import get_http_client
from app.schemas.task import TaskCreate, TaskListResponse, TaskResponse, TaskUpdate
from app.services.n8n_service import N8nService
from app.services.task_service import TaskService

router = APIRouter()


# ── Dependencies ───────────────────────────────────────────


def get_task_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TaskService:
    return TaskService(db)


def get_n8n_service() -> N8nService:
    return N8nService(get_http_client())


# ── Endpoints ──────────────────────────────────────────────


@router.post(
    "/",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une tâche et l'envoyer au worker Celery",
)
async def create_task(
    data: TaskCreate,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskResponse:
    """
    Persiste la tâche en DB puis l'envoie immédiatement à Celery via Redis.
    La réponse est retournée sans attendre la fin du traitement.
    Appelé typiquement par un nœud HTTP Request de n8n.
    """
    from app.workers.tasks import run_task

    task = await service.create(data)

    # Envoi au worker — non bloquant, découplé du process FastAPI
    run_task.delay(str(task.id), task.task_type, task.payload or {})

    return TaskResponse.model_validate(task)


@router.get("/", response_model=TaskListResponse, summary="Lister les tâches")
async def list_tasks(
    service: Annotated[TaskService, Depends(get_task_service)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    task_type: str | None = Query(None),
) -> TaskListResponse:
    tasks, total = await service.list(page=page, size=size, status=status, task_type=task_type)
    return TaskListResponse(
        items=[TaskResponse.model_validate(t) for t in tasks],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{task_id}", response_model=TaskResponse, summary="Récupérer une tâche par ID")
async def get_task(
    task_id: uuid.UUID,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskResponse:
    """Point de polling pour n8n — interroge jusqu'à status=success/failed."""
    task = await service.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse.model_validate(task)


@router.patch("/{task_id}", response_model=TaskResponse, summary="Mettre à jour statut / résultat")
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdate,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskResponse:
    """
    Endpoint de callback — n8n peut PATCH cette route pour signaler
    l'état d'une exécution externe ou enrichir le résultat.
    """
    task = await service.update(task_id, data)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une tâche")
async def delete_task(
    task_id: uuid.UUID,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> None:
    deleted = await service.delete(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")


@router.post(
    "/{task_id}/trigger-n8n",
    response_model=dict,
    summary="Envoyer une tâche existante vers un webhook n8n",
)
async def trigger_n8n_workflow(
    task_id: uuid.UUID,
    service: Annotated[TaskService, Depends(get_task_service)],
    n8n: Annotated[N8nService, Depends(get_n8n_service)],
    webhook_path: str = Query(..., description="Chemin du webhook n8n à appeler"),
) -> dict:
    """
    Relit une tâche existante et envoie son payload vers un webhook n8n.
    Utile pour re-déclencher un workflow avec les données déjà stockées.
    """
    task = await service.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await n8n.trigger_webhook(
        webhook_path,
        {
            "task_id": str(task.id),
            "task_type": task.task_type,
            "payload": task.payload,
        },
    )
    return {"triggered": True, "n8n_response": result}
