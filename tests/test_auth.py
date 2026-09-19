from fastapi.testclient import TestClient


def test_register_success(client: TestClient):
    """Test standard user registration succeeds with 201 Created."""
    payload = {
        "email": "newuser@example.com",
        "password": "strongPassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["email"] == "newuser@example.com"
    assert "created_at" in data
    # Password hash must not be leaked
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_email(client: TestClient, test_user_a):
    """Test duplicate registration returns 409 Conflict."""
    payload = {
        "email": test_user_a.email,
        "password": "anotherPassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert "detail" in data
    assert "already exists" in data["detail"].lower()


def test_register_invalid_short_password(client: TestClient):
    """Test short password is rejected with 422 validation error."""
    payload = {
        "email": "shortpass@example.com",
        "password": "123",  # Less than 6 characters
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_login_success(client: TestClient, test_user_a):
    """Test authentication succeeds and returns valid JWT token."""
    payload = {
        "email": test_user_a.email,
        "password": "PasswordA123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"].lower() == "bearer"
    assert len(data["access_token"]) > 20


def test_login_wrong_password(client: TestClient, test_user_a):
    """Test authentication fails on bad password with 401 Unauthorized."""
    payload = {
        "email": test_user_a.email,
        "password": "WrongPassword999!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401


def test_login_nonexistent_user(client: TestClient):
    """Test authentication fails for unknown email with 401 Unauthorized."""
    payload = {
        "email": "nobody@example.com",
        "password": "RandomPassword!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401


def test_get_me_profile(client: TestClient, test_user_a, auth_headers_user_a):
    """Test authenticated /auth/me returns current user profile."""
    response = client.get("/api/v1/auth/me", headers=auth_headers_user_a)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(test_user_a.id)
    assert data["email"] == test_user_a.email


def test_get_me_unauthorized(client: TestClient):
    """Test /auth/me without authorization header returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_get_me_invalid_token(client: TestClient):
    """Test /auth/me with invalid token signature returns 401."""
    headers = {"Authorization": "Bearer invalid.jwt.token.string"}
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
