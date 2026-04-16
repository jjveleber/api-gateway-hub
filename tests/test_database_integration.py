import pytest
from testcontainers.postgres import PostgresContainer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import uuid

from app.models.database import Base
from app.models.request_log import APIRequestLog


@pytest.fixture(scope="session")
def postgres_container():
    """Start PostgreSQL container for tests."""
    with PostgresContainer("postgres:16") as postgres:
        yield postgres


@pytest.fixture
async def test_engine(postgres_container):
    """Create test database engine."""
    # Build asyncpg connection URL
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    user = postgres_container.username
    password = postgres_container.password
    db = postgres_container.dbname
    async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"

    engine = create_async_engine(async_url, echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """Create database session for each test."""
    async_session = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session
        await session.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_request_log(db_session):
    """Test creating an API request log entry."""
    log_entry = APIRequestLog(
        request_id=uuid.uuid4(),
        endpoint="/api/weather",
        params={"city": "London"},
        external_api="openweather",
        cached=False,
        response_time_ms=250,
        status=200,
    )

    db_session.add(log_entry)
    await db_session.commit()

    assert log_entry.id is not None
    assert log_entry.endpoint == "/api/weather"
    assert log_entry.external_api == "openweather"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_request_logs(db_session):
    """Test querying API request logs."""
    from sqlalchemy import select

    # Create multiple log entries
    for i in range(3):
        log = APIRequestLog(
            request_id=uuid.uuid4(),
            endpoint=f"/api/test{i}",
            external_api="testapi",
            cached=(i % 2 == 0),
            status=200,
        )
        db_session.add(log)

    await db_session.commit()

    # Query cached requests
    result = await db_session.execute(
        select(APIRequestLog).where(APIRequestLog.cached == True)
    )
    cached_logs = result.scalars().all()

    assert len(cached_logs) == 2  # Entries 0 and 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_request_log_with_error(db_session):
    """Test logging failed API requests."""
    log_entry = APIRequestLog(
        request_id=uuid.uuid4(),
        endpoint="/api/weather",
        params={"city": "InvalidCity"},
        external_api="openweather",
        cached=False,
        status=503,
        error_message="Service unavailable",
    )

    db_session.add(log_entry)
    await db_session.commit()

    assert log_entry.status == 503
    assert log_entry.error_message == "Service unavailable"
