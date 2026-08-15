"""Auth / account management."""

from sonicverse.core.auth import AuthUser, hash_password, issue_token


async def test_status_setup_required(anon_client):
    response = await anon_client.get("/api/v1/auth/status")
    assert response.status_code == 200
    assert response.json() == {"setup_required": True, "user": None}


async def test_bootstrap_admin_and_login(anon_client):
    created = await anon_client.post(
        "/api/v1/users",
        json={"username": "root", "password": "secret1", "role": "user"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["username"] == "root"
    assert body["role"] == "admin"

    login = await anon_client.post(
        "/api/v1/auth/login",
        json={"username": "root", "password": "secret1"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    status = await anon_client.get(
        "/api/v1/auth/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status.json()["setup_required"] is False
    assert status.json()["user"]["username"] == "root"


async def test_unauthenticated_api_is_blocked(anon_client):
    response = await anon_client.get("/api/v1/stats")
    assert response.status_code == 401


async def test_health_stays_public(anon_client):
    response = await anon_client.get("/health")
    assert response.status_code == 200


async def test_admin_creates_user(client):
    created = await client.post(
        "/api/v1/users",
        json={"username": "alice", "password": "alice12", "role": "user"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "user"

    listed = await client.get("/api/v1/users")
    names = {item["username"] for item in listed.json()["users"]}
    assert names == {"admin", "alice"}


async def test_regular_user_cannot_create(client):
    created = await client.post(
        "/api/v1/users",
        json={"username": "bob", "password": "bobbob1", "role": "user"},
    )
    assert created.status_code == 201
    bob = created.json()
    token = issue_token(
        AuthUser(id=bob["id"], username=bob["username"], role=bob["role"])
    )
    denied = await client.post(
        "/api/v1/users",
        json={"username": "carol", "password": "carol12", "role": "user"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403


async def test_cannot_delete_last_admin(client):
    response = await client.get("/api/v1/users")
    admin = next(item for item in response.json()["users"] if item["role"] == "admin")
    deleted = await client.delete(f"/api/v1/users/{admin['id']}")
    assert deleted.status_code == 400
    assert "最后一个管理员" in deleted.json()["detail"]


async def test_disable_blocks_login(client, anon_client):
    created = await client.post(
        "/api/v1/users",
        json={"username": "paused", "password": "paused1", "role": "user"},
    )
    user_id = created.json()["id"]
    patched = await client.patch(f"/api/v1/users/{user_id}", json={"disabled": True})
    assert patched.status_code == 200
    assert patched.json()["disabled"] is True

    login = await anon_client.post(
        "/api/v1/auth/login",
        json={"username": "paused", "password": "paused1"},
    )
    assert login.status_code == 401


async def test_admin_resets_password(client, anon_client):
    created = await client.post(
        "/api/v1/users",
        json={"username": "dave", "password": "oldpass1", "role": "user"},
    )
    user_id = created.json()["id"]
    reset = await client.put(
        f"/api/v1/users/{user_id}/password",
        json={"new_password": "newpass1"},
    )
    assert reset.status_code == 200
    login = await anon_client.post(
        "/api/v1/auth/login",
        json={"username": "dave", "password": "newpass1"},
    )
    assert login.status_code == 200
