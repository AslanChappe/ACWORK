"""Tests des endpoints /api/v1/tasks/ — CRUD, auth, pagination, filtres, edge cases."""

import pytest
from httpx import AsyncClient

# ── Santé ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ping(client: AsyncClient):
    response = await client.get("/api/v1/ping")
    assert response.status_code == 200
    assert response.json() == {"pong": "ok"}


# ── Authentification ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_required_without_key():
    """Sans header X-API-Key, les endpoints tasks retournent 401."""
    from unittest.mock import MagicMock, patch

    from httpx import ASGITransport
    from httpx import AsyncClient as AC

    from app.main import app as main_app
    from tests.conftest import TEST_API_KEY

    with patch("app.core.security.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(internal_api_key=TEST_API_KEY, is_dev=False)
        async with AC(
            transport=ASGITransport(app=main_app), base_url="http://test"
        ) as no_key_client:
            response = await no_key_client.get("/api/v1/tasks/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_wrong_key_returns_401():
    """Un mauvais X-API-Key retourne 401."""
    from unittest.mock import MagicMock, patch

    from httpx import ASGITransport
    from httpx import AsyncClient as AC

    from app.main import app as main_app
    from tests.conftest import TEST_API_KEY

    with patch("app.core.security.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(internal_api_key=TEST_API_KEY, is_dev=False)
        async with AC(
            transport=ASGITransport(app=main_app),
            base_url="http://test",
            headers={"X-API-Key": "wrong-key"},
        ) as bad_client:
            response = await bad_client.get("/api/v1/tasks/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_is_always_public():
    """L'endpoint health ne nécessite pas d'authentification."""
    from unittest.mock import MagicMock, patch

    from httpx import ASGITransport
    from httpx import AsyncClient as AC

    from app.main import app as main_app
    from tests.conftest import TEST_API_KEY

    with patch("app.core.security.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(internal_api_key=TEST_API_KEY, is_dev=False)
        with patch("app.api.v1.endpoints.health.get_http_client") as mock_http:
            mock_http.return_value.get = MagicMock()
            async with AC(
                transport=ASGITransport(app=main_app), base_url="http://test"
            ) as no_key_client:
                response = await no_key_client.get("/api/v1/health")
    assert response.status_code == 200


# ── Création ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_minimal(client: AsyncClient):
    """Création avec les champs minimaux requis."""
    response = await client.post(
        "/api/v1/tasks/",
        json={"name": "Ma tâche", "task_type": "test"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Ma tâche"
    assert data["task_type"] == "test"
    assert data["status"] == "pending"
    assert data["id"] is not None
    assert data["created_at"] is not None


@pytest.mark.asyncio
async def test_create_task_with_payload(client: AsyncClient):
    """Création avec un payload arbitraire."""
    response = await client.post(
        "/api/v1/tasks/",
        json={
            "name": "Analyse texte",
            "task_type": "text_analysis",
            "payload": {"text": "Bonjour le monde", "lang": "fr"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["payload"]["text"] == "Bonjour le monde"
    assert data["payload"]["lang"] == "fr"


@pytest.mark.asyncio
async def test_create_task_triggers_celery(client: AsyncClient, mock_celery_task):
    """La création doit déclencher run_task.delay()."""
    await client.post(
        "/api/v1/tasks/",
        json={"name": "Celery test", "task_type": "test"},
    )
    mock_celery_task.delay.assert_called_once()
    call_args = mock_celery_task.delay.call_args[0]
    assert call_args[1] == "test"  # task_type


@pytest.mark.asyncio
async def test_create_task_missing_name_returns_422(client: AsyncClient):
    """Un payload sans 'name' doit retourner 422."""
    response = await client.post(
        "/api/v1/tasks/",
        json={"task_type": "test"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_task_missing_task_type_returns_422(client: AsyncClient):
    """Un payload sans 'task_type' doit retourner 422."""
    response = await client.post(
        "/api/v1/tasks/",
        json={"name": "Sans type"},
    )
    assert response.status_code == 422


# ── Lecture ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_task_by_id(client: AsyncClient):
    """GET /tasks/{id} retourne la bonne tâche."""
    create_resp = await client.post(
        "/api/v1/tasks/",
        json={"name": "À récupérer", "task_type": "fetch_test"},
    )
    task_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["id"] == task_id
    assert response.json()["name"] == "À récupérer"


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient):
    """GET sur un UUID inexistant retourne 404."""
    response = await client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_task_invalid_uuid(client: AsyncClient):
    """GET avec un ID non-UUID retourne 422."""
    response = await client.get("/api/v1/tasks/not-a-uuid")
    assert response.status_code == 422


# ── Liste + pagination ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tasks_returns_structure(client: AsyncClient):
    """GET /tasks/ retourne la structure attendue."""
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "size" in data


@pytest.mark.asyncio
async def test_list_tasks_pagination(client: AsyncClient):
    """La pagination page/size fonctionne correctement."""
    # Créer 5 tâches
    for i in range(5):
        await client.post(
            "/api/v1/tasks/",
            json={"name": f"Pagination {i}", "task_type": "pagination_test"},
        )

    page1 = await client.get("/api/v1/tasks/?page=1&size=2&task_type=pagination_test")
    page2 = await client.get("/api/v1/tasks/?page=2&size=2&task_type=pagination_test")

    assert page1.status_code == 200
    assert page2.status_code == 200

    data1 = page1.json()
    data2 = page2.json()

    assert len(data1["items"]) == 2
    assert len(data2["items"]) == 2
    assert data1["total"] >= 5

    # Les IDs des deux pages doivent être différents
    ids_p1 = {t["id"] for t in data1["items"]}
    ids_p2 = {t["id"] for t in data2["items"]}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status(client: AsyncClient):
    """Le filtre ?status= retourne uniquement les tâches correspondantes."""
    # Créer une tâche et la passer en running
    create_resp = await client.post(
        "/api/v1/tasks/",
        json={"name": "À filtrer", "task_type": "filter_test"},
    )
    task_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/tasks/{task_id}", json={"status": "running"})

    response = await client.get("/api/v1/tasks/?status=running")
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(t["status"] == "running" for t in items)


@pytest.mark.asyncio
async def test_list_tasks_filter_by_type(client: AsyncClient):
    """Le filtre ?task_type= retourne uniquement les tâches du bon type."""
    await client.post(
        "/api/v1/tasks/",
        json={"name": "Type A", "task_type": "type_filter_unique_a"},
    )

    response = await client.get("/api/v1/tasks/?task_type=type_filter_unique_a")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    assert all(t["task_type"] == "type_filter_unique_a" for t in items)


@pytest.mark.asyncio
async def test_list_tasks_size_limit(client: AsyncClient):
    """size > 100 retourne 422."""
    response = await client.get("/api/v1/tasks/?size=101")
    assert response.status_code == 422


# ── Mise à jour ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_task_status(client: AsyncClient):
    """PATCH met à jour le statut."""
    create_resp = await client.post(
        "/api/v1/tasks/",
        json={"name": "À mettre à jour", "task_type": "update_test"},
    )
    task_id = create_resp.json()["id"]

    update_resp = await client.patch(f"/api/v1/tasks/{task_id}", json={"status": "running"})
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_update_task_result(client: AsyncClient):
    """PATCH peut écrire un résultat."""
    create_resp = await client.post(
        "/api/v1/tasks/",
        json={"name": "Résultat", "task_type": "result_test"},
    )
    task_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "success", "result": {"score": 0.95, "label": "positive"}},
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["status"] == "success"
    assert data["result"]["score"] == 0.95


@pytest.mark.asyncio
async def test_update_task_not_found(client: AsyncClient):
    """PATCH sur un UUID inexistant retourne 404."""
    response = await client.patch(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000",
        json={"status": "running"},
    )
    assert response.status_code == 404


# ── Suppression ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient):
    """DELETE supprime la tâche — GET suivant retourne 404."""
    create_resp = await client.post(
        "/api/v1/tasks/",
        json={"name": "À supprimer", "task_type": "delete_test"},
    )
    task_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_not_found(client: AsyncClient):
    """DELETE sur un UUID inexistant retourne 404."""
    response = await client.delete("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_twice_returns_404(client: AsyncClient):
    """Supprimer deux fois la même tâche — la deuxième retourne 404."""
    create_resp = await client.post(
        "/api/v1/tasks/",
        json={"name": "Double delete", "task_type": "delete_test"},
    )
    task_id = create_resp.json()["id"]

    await client.delete(f"/api/v1/tasks/{task_id}")
    second_delete = await client.delete(f"/api/v1/tasks/{task_id}")
    assert second_delete.status_code == 404
