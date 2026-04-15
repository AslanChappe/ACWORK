"""Tests de la couche service TaskService — logique métier isolée des endpoints."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task_service import TaskService

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _create(service: TaskService, **kwargs) -> object:
    defaults = {"name": "Tâche de test", "task_type": "unit_test"}
    defaults.update(kwargs)
    return await service.create(TaskCreate(**defaults))


# ── Create ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_sets_pending_status(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service)
    assert task.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_create_stores_payload(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service, payload={"key": "value", "number": 42})
    assert task.payload["key"] == "value"
    assert task.payload["number"] == 42


@pytest.mark.asyncio
async def test_create_assigns_uuid(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service)
    assert task.id is not None
    assert isinstance(task.id, uuid.UUID)


@pytest.mark.asyncio
async def test_create_stores_n8n_execution_id(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service, n8n_execution_id="n8n-exec-123")
    assert task.n8n_execution_id == "n8n-exec-123"


# ── Read ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_by_id_returns_task(db_session: AsyncSession):
    service = TaskService(db_session)
    created = await _create(service)
    fetched = await service.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == created.name


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown(db_session: AsyncSession):
    service = TaskService(db_session)
    result = await service.get_by_id(uuid.uuid4())
    assert result is None


# ── List ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_tasks_and_total(db_session: AsyncSession):
    service = TaskService(db_session)
    for _ in range(3):
        await _create(service, name="Liste", task_type="list_test_unique")

    tasks, total = await service.list(task_type="list_test_unique")
    assert total >= 3
    assert len(tasks) >= 3


@pytest.mark.asyncio
async def test_list_pagination(db_session: AsyncSession):
    service = TaskService(db_session)
    for _ in range(4):
        await _create(service, task_type="pagination_service_test")

    page1, total = await service.list(page=1, size=2, task_type="pagination_service_test")
    page2, _ = await service.list(page=2, size=2, task_type="pagination_service_test")

    assert len(page1) == 2
    assert len(page2) == 2
    assert total >= 4

    ids_p1 = {t.id for t in page1}
    ids_p2 = {t.id for t in page2}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_list_filter_by_status(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service, task_type="status_filter_test")
    await service.mark_running(task.id)

    running_tasks, _ = await service.list(status="running", task_type="status_filter_test")
    assert any(t.id == task.id for t in running_tasks)

    pending_tasks, _ = await service.list(status="pending", task_type="status_filter_test")
    assert not any(t.id == task.id for t in pending_tasks)


# ── Update ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_status(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service)
    updated = await service.update(task.id, TaskUpdate(status=TaskStatus.RUNNING))
    assert updated.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_update_sets_started_at_on_running(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service)
    assert task.started_at is None
    updated = await service.mark_running(task.id)
    assert updated.started_at is not None


@pytest.mark.asyncio
async def test_update_sets_finished_at_on_success(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service)
    await service.mark_running(task.id)
    updated = await service.mark_success(task.id, {"score": 1.0})
    assert updated.status == TaskStatus.SUCCESS
    assert updated.finished_at is not None
    assert updated.result == {"score": 1.0}


@pytest.mark.asyncio
async def test_update_sets_finished_at_on_failure(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service)
    updated = await service.mark_failed(task.id, "Timeout error")
    assert updated.status == TaskStatus.FAILED
    assert updated.finished_at is not None
    assert updated.error_message == "Timeout error"


@pytest.mark.asyncio
async def test_update_not_found_returns_none(db_session: AsyncSession):
    service = TaskService(db_session)
    result = await service.update(uuid.uuid4(), TaskUpdate(status=TaskStatus.RUNNING))
    assert result is None


@pytest.mark.asyncio
async def test_update_partial_fields(db_session: AsyncSession):
    """PATCH partiel — seuls les champs fournis sont modifiés."""
    service = TaskService(db_session)
    task = await _create(service, name="Original")
    updated = await service.update(task.id, TaskUpdate(status=TaskStatus.RUNNING))
    # Le nom ne doit pas avoir changé
    assert updated.name == "Original"


# ── Delete ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_removes_task(db_session: AsyncSession):
    service = TaskService(db_session)
    task = await _create(service)
    deleted = await service.delete(task.id)
    assert deleted is True
    fetched = await service.get_by_id(task.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_delete_not_found_returns_false(db_session: AsyncSession):
    service = TaskService(db_session)
    result = await service.delete(uuid.uuid4())
    assert result is False


# ── Helpers mark_* ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_running_twice_keeps_started_at(db_session: AsyncSession):
    """mark_running ne doit pas écraser started_at si déjà défini."""
    service = TaskService(db_session)
    task = await _create(service)
    first = await service.mark_running(task.id)
    started_at_first = first.started_at

    second = await service.mark_running(task.id)
    assert second.started_at == started_at_first
