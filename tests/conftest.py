import base64
import os
import shutil
import tempfile
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db, get_storage_service
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.main import app
from app.models.user import User
from app.services.storage.local import LocalStorageService
from app.workers.celery_app import celery_app

# Force Celery to execute eagerly for unit tests
celery_app.conf.update(task_always_eager=True)

# Test SQLite in-memory database with StaticPool to share connection across threads
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create all tables before test session and drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide clean database session with transaction rollback after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for uploaded files during tests."""
    temp_dir = tempfile.mkdtemp(prefix="test_uploads_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def client(db_session: Session, temp_storage_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with dependency overrides for DB session and local storage."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_storage_service():
        return LocalStorageService(temp_storage_dir)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage_service] = override_get_storage_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def test_user_a(db_session: Session) -> User:
    """Fixture to create primary test user."""
    user = User(
        email="usera@example.com",
        password_hash=hash_password("PasswordA123!"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers_user_a(test_user_a: User) -> dict:
    """Bearer token headers for User A."""
    token = create_access_token(
        subject=str(test_user_a.id),
        claims={"email": test_user_a.email},
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_user_b(db_session: Session) -> User:
    """Fixture to create secondary test user for multi-tenant isolation tests."""
    user = User(
        email="userb@example.com",
        password_hash=hash_password("PasswordB123!"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers_user_b(test_user_b: User) -> dict:
    """Bearer token headers for User B."""
    token = create_access_token(
        subject=str(test_user_b.id),
        claims={"email": test_user_b.email},
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid PDF byte sequence."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 72 712 Td (Sample Question Paper) Tj ET\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000204 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n298\n%%EOF\n"
    )


@pytest.fixture
def sample_png_bytes() -> bytes:
    """Minimal valid 1x1 PNG byte sequence."""
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    return base64.b64decode(png_b64)


@pytest.fixture
def sample_jpg_bytes() -> bytes:
    """Minimal valid 1x1 JPEG byte sequence."""
    jpg_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
    return base64.b64decode(jpg_b64)
