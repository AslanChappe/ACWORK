"""Integration tests for the tasks API."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_ping(client: AsyncClient):
    response = await client.get("/api/v1/ping")
    assert response.status_code == 200
    assert response.json() == {"pong": "ok"}


@pytest.mark.asyncio
async def test_create_task(client: AsyncClient):
    payload = {
        "name": "Test task",
        "task_type": "test",
        "payload": {"key": "value"},
    }
    response = await client.post("/api/v1/tasks/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test task"
    assert data["task_type"] == "test"
    assert data["status"] == "pending"
    return data["id"]


@pytest.mark.asyncio
async def test_get_task(client: AsyncClient):
    # First create a task
    create_resp = await client.post("/api/v1/tasks/", json={
        "name": "Fetch me",
        "task_type": "fetch_test",
    })
    task_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["id"] == task_id


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient):
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_update_task(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks/", json={
        "name": "Update me",
        "task_type": "update_test",
    })
    task_id = create_resp.json()["id"]

    update_resp = await client.patch(f"/api/v1/tasks/{task_id}", json={
        "status": "running",
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks/", json={
        "name": "Delete me",
        "task_type": "delete_test",
    })
    task_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 404
