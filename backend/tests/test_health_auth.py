"""Health and auth tests."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "fake"


def test_register_login_me(client):
    email = "auth_flow@example.com"
    password = "strong-password-1"

    r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "full_name": "A"})
    assert r.status_code == 201
    tokens = r.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == email

    # Refresh rotation works and old refresh token is revoked.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401


def test_register_duplicate_conflict(client):
    payload = {"email": "dup@example.com", "password": "strong-password-1"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={"email": "weak@example.com", "password": "short"})
    assert r.status_code == 422
