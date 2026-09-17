import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AUTH_TEST_MODE", "true")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.main import app as fastapi_app
import app.models


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def db_override():
        async with sessions() as session:
            yield session

    settings = Settings(database_url="sqlite+aiosqlite://", environment="test", auth_test_mode=True, career_ops_workspace_root=tmp_path / "users", career_ops_code_root=tmp_path / "code")
    fastapi_app.dependency_overrides[get_db] = db_override
    fastapi_app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        yield client, sessions, settings
    fastapi_app.dependency_overrides.clear()
    await engine.dispose()
