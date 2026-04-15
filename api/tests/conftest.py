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

# Force development mode pour les tests — désactive l'auth quand INTERNAL_API_KEY absent
os.environ.setdefault("API_ENV", "development")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key-for-tests-minimum-32-chars")
os.environ["SENTRY_DSN"] = ""  # désactive Sentry pendant les tests

from collections.abc import AsyncGenerator  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import verify_api_key  # noqa: E402
from app.main import app as main_app  # noqa: E402

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)

# Clé utilisée dans les fixtures authentifiées
TEST_API_KEY = "test-internal-api-key-for-tests"


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
    """Mock run_task.delay() — empêche les appels au broker Redis pendant les tests."""
    mock = MagicMock()
    mock.delay = MagicMock(return_value=MagicMock(id="test-celery-task-id"))
    with patch("app.workers.tasks.run_task", mock):
        yield mock


@pytest.fixture
def mock_http_client_init():
    """
    Mock init_http_client et get_http_client — le lifespan FastAPI n'est pas
    déclenché dans les tests, donc le client HTTP doit être mocké.
    """
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=MagicMock(status_code=200))
    with (
        patch("app.core.http_client.get_http_client", return_value=fake_client),
        patch("app.api.v1.endpoints.health.get_http_client", return_value=fake_client),
    ):
        yield fake_client


@pytest.fixture
async def client(
    db_session: AsyncSession,
    mock_celery_task,
    mock_http_client_init,
) -> AsyncGenerator[AsyncClient, None]:
    """Client sans authentification — la dépendance verify_api_key est bypassée."""

    async def _no_auth():
        return None

    def override_get_db():
        yield db_session

    main_app.dependency_overrides[get_db] = override_get_db
    main_app.dependency_overrides[verify_api_key] = _no_auth
    async with AsyncClient(
        transport=ASGITransport(app=main_app),
        base_url="http://test",
    ) as ac:
        yield ac
    main_app.dependency_overrides.clear()


@pytest.fixture
async def authed_client(
    db_session: AsyncSession,
    mock_celery_task,
    mock_http_client_init,
) -> AsyncGenerator[AsyncClient, None]:
    """Client avec X-API-Key — simule les appels n8n → FastAPI en production."""

    def override_get_db():
        yield db_session

    main_app.dependency_overrides[get_db] = override_get_db

    with patch("app.core.security.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            internal_api_key=TEST_API_KEY,
            is_dev=False,
        )
        async with AsyncClient(
            transport=ASGITransport(app=main_app),
            base_url="http://test",
            headers={"X-API-Key": TEST_API_KEY},
        ) as ac:
            yield ac
    main_app.dependency_overrides.clear()


@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient pour les tests N8nService."""
    return AsyncMock()
