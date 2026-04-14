"""
Test configuration.

Par défaut, les tests utilisent SQLite en mémoire — aucun Docker requis.
Pour tester sur PostgreSQL (stack locale allumée) :
  TEST_DATABASE_URL="postgresql+asyncpg://admin:local_password@localhost:5434/appdb" pytest

Drivers requis :
  - SQLite  : aiosqlite  (inclus dans [dev])
  - Postgres: asyncpg    (inclus dans les deps principales)
"""
import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app as main_app

# SQLite en mémoire par défaut → zéro configuration nécessaire en local
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def engine():
    connect_args = {"check_same_thread": False} if "sqlite" in TEST_DATABASE_URL else {}
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False, connect_args=connect_args)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def mock_celery_task():
    """
    Mock run_task.delay() — empêche les appels au broker Redis pendant les tests.
    La tâche reste en status 'pending' (le worker ne tourne pas en tests unitaires).
    """
    mock = MagicMock()
    mock.delay = MagicMock(return_value=MagicMock(id="test-celery-task-id"))
    with patch("app.api.v1.endpoints.tasks.run_task", mock):
        yield mock


@pytest.fixture
async def client(
    db_session: AsyncSession,
    mock_celery_task,           # injecté automatiquement → Celery toujours mocké
) -> AsyncGenerator[AsyncClient, None]:
    def override_get_db():
        yield db_session

    main_app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=main_app),
        base_url="http://test",
    ) as ac:
        yield ac
    main_app.dependency_overrides.clear()
