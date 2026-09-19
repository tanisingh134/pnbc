from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """Test /health endpoint returns HTTP 200 and system indicators."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "app_name" in data
    assert "environment" in data
    assert "database" in data
    assert "redis" in data
    # Database is connected via test session
    assert data["database"] == "connected"


def test_root_endpoint(client: TestClient):
    """Test / root endpoint returns service info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert data["docs"] == "/docs"
    assert data["health"] == "/health"
