"""
TaskService — async CRUD + business logic for tasks.
Inject via FastAPI Depends().
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.task import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate

logger = get_logger(__name__)


class TaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Create ─────────────────────────────────────────────
    async def create(self, data: TaskCreate) -> Task:
        task = Task(
            name=data.name,
            task_type=data.task_type,
            status=TaskStatus.PENDING,
            payload=data.payload,
            n8n_execution_id=data.n8n_execution_id,
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        logger.info("task.created", task_id=str(task.id), task_type=task.task_type)
        return task

    # ── Read ───────────────────────────────────────────────
    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        result = await self.db.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        task_type: str | None = None,
    ) -> tuple[list[Task], int]:
        query = select(Task)
        count_query = select(func.count()).select_from(Task)

        if status:
            query = query.where(Task.status == status)
            count_query = count_query.where(Task.status == status)
        if task_type:
            query = query.where(Task.task_type == task_type)
            count_query = count_query.where(Task.task_type == task_type)

        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(Task.created_at.desc())
        query = query.offset((page - 1) * size).limit(size)

        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    # ── Update ─────────────────────────────────────────────
    async def update(self, task_id: uuid.UUID, data: TaskUpdate) -> Task | None:
        task = await self.get_by_id(task_id)
        if not task:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(task, field, value)

        # Auto-set timestamps based on status transition
        if data.status == TaskStatus.RUNNING and not task.started_at:
            task.started_at = datetime.now(UTC)
        if data.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.finished_at = datetime.now(UTC)

        await self.db.flush()
        await self.db.refresh(task)
        logger.info("task.updated", task_id=str(task_id), status=task.status)
        return task

    # ── Delete ─────────────────────────────────────────────
    async def delete(self, task_id: uuid.UUID) -> bool:
        task = await self.get_by_id(task_id)
        if not task:
            return False
        await self.db.delete(task)
        await self.db.flush()
        logger.info("task.deleted", task_id=str(task_id))
        return True

    # ── Helpers ────────────────────────────────────────────
    async def mark_running(self, task_id: uuid.UUID) -> Task | None:
        return await self.update(task_id, TaskUpdate(status=TaskStatus.RUNNING))

    async def mark_success(self, task_id: uuid.UUID, result: dict) -> Task | None:
        return await self.update(task_id, TaskUpdate(status=TaskStatus.SUCCESS, result=result))

    async def mark_failed(self, task_id: uuid.UUID, error: str) -> Task | None:
        return await self.update(task_id, TaskUpdate(status=TaskStatus.FAILED, error_message=error))
