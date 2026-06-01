import os
import sys
import io
import tempfile

os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test123"
os.environ["APP_SESSION_SECRET"] = "test-secret-key-for-testing-32chars!"
os.environ["SECRET_TOKEN"] = "test-worker-token"

from app import create_app
import pytest


@pytest.fixture
def app():
    app = create_app(instance_path=tempfile.mkdtemp())
    app.config["TESTING"] = True
    app.config["downloads_dir"] = tempfile.mkdtemp()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# === Auth ===

def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "BBDown" in resp.get_data(as_text=True)


def test_login_admin_success(client):
    resp = client.post("/api/login", json={"username": "admin", "password": "test123"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["is_admin"] is True


def test_login_wrong_password(client):
    resp = client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_empty_fields(client):
    resp = client.post("/api/login", json={"username": "", "password": ""})
    assert resp.status_code == 400


def test_login_rate_limit(client):
    for _ in range(5):
        client.post("/api/login", json={"username": "admin", "password": "wrong"})
    resp = client.post("/api/login", json={"username": "admin", "password": "test123"})
    assert resp.status_code == 429


def test_unauthenticated_redirect(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_logout(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.post("/api/logout")
    assert resp.status_code == 200
    resp2 = client.get("/")
    assert resp2.status_code == 302


# === Download API ===

def test_download_requires_auth(client):
    resp = client.post("/api/download", json={"url": "BV123", "mode": "audio"})
    assert resp.status_code == 401


def test_download_empty_url(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.post("/api/download", json={"url": "", "mode": "audio"})
    assert resp.status_code == 400


def test_download_success(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.post("/api/download", json={"url": "BV123", "mode": "audio"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "task_id" in data
    assert "warning" in data  # no B站 login


def test_download_default_mode(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.post("/api/download", json={"url": "BV123"})
    assert resp.status_code == 200
    assert "task_id" in resp.get_json()


def test_tasks_list(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_status(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert "bilibili_logged_in" in resp.get_json()


def test_file_not_found(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.get("/api/file/nonexistent")
    assert resp.status_code == 404


def test_login_bilibili(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.post("/api/login-bilibili")
    assert resp.status_code == 200
    assert "task_id" in resp.get_json()


# === Worker API ===

def test_worker_poll_no_token(client):
    resp = client.get("/api/worker/poll")
    assert resp.status_code == 403


def test_worker_poll_empty(client):
    resp = client.get("/api/worker/poll", headers={"Authorization": "Bearer test-worker-token"})
    assert resp.status_code == 200
    assert resp.get_json()["type"] == "wait"


def test_worker_poll_gets_task(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    client.post("/api/download", json={"url": "BV123", "mode": "audio"})
    resp = client.get("/api/worker/poll", headers={"Authorization": "Bearer test-worker-token"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "download"
    assert data["url"] == "BV123"


def test_worker_poll_gets_login(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    client.post("/api/login-bilibili")
    resp = client.get("/api/worker/poll", headers={"Authorization": "Bearer test-worker-token"})
    assert resp.status_code == 200
    assert resp.get_json()["type"] == "login"


def test_worker_progress(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    r = client.post("/api/download", json={"url": "BV123", "mode": "audio"})
    tid = r.get_json()["task_id"]

    client.post(f"/api/worker/progress/{tid}",
                json={"title": "Test", "progress": 0.5, "speed": "5 MB/s"},
                headers={"Authorization": "Bearer test-worker-token"})

    tasks = client.get("/api/tasks").get_json()
    task = [t for t in tasks if t["id"] == tid][0]
    assert task["status"] == "downloading"
    assert task["progress"] == 0.5


def test_worker_fail(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    r = client.post("/api/download", json={"url": "BV123", "mode": "audio"})
    tid = r.get_json()["task_id"]

    client.post(f"/api/worker/fail/{tid}",
                json={"error": "404 not found"},
                headers={"Authorization": "Bearer test-worker-token"})

    tasks = client.get("/api/tasks").get_json()
    task = [t for t in tasks if t["id"] == tid][0]
    assert task["status"] == "failed"


def test_worker_login_success(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    r = client.post("/api/login-bilibili")
    tid = r.get_json()["task_id"]

    client.post(f"/api/worker/login-success/{tid}",
                headers={"Authorization": "Bearer test-worker-token"})
    assert client.application.config["bilibili_logged_in"] is True


def test_worker_complete_upload(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    r = client.post("/api/download", json={"url": "BV123", "mode": "audio"})
    tid = r.get_json()["task_id"]

    data = {"file": (io.BytesIO(b"fake mp4"), "test_video.mp4")}
    client.post(f"/api/worker/complete/{tid}", data=data,
                headers={"Authorization": "Bearer test-worker-token"},
                content_type="multipart/form-data")

    tasks = client.get("/api/tasks").get_json()
    task = [t for t in tasks if t["id"] == tid][0]
    assert task["status"] == "completed"
    assert os.path.exists(task["file_path"])


def test_worker_cookie_status(client, app):
    client.get("/api/worker/poll?cookie_available=true",
               headers={"Authorization": "Bearer test-worker-token"})
    assert app.config["bilibili_logged_in"] is True

    client.get("/api/worker/poll?cookie_available=false",
               headers={"Authorization": "Bearer test-worker-token"})
    assert app.config["bilibili_logged_in"] is False


# === User management ===

def test_user_add(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.post("/api/users/add", json={"username": "bob", "password": "hello"})
    assert resp.status_code == 200
    users = client.get("/api/users").get_json()
    assert "bob" in users


def test_user_add_duplicate(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    client.post("/api/users/add", json={"username": "charlie", "password": "x"})
    resp = client.post("/api/users/add", json={"username": "charlie", "password": "y"})
    assert resp.status_code == 409


def test_user_remove(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    client.post("/api/users/add", json={"username": "dave", "password": "x"})
    client.post("/api/users/remove", json={"username": "dave"})
    users = client.get("/api/users").get_json()
    assert "dave" not in users


def test_cannot_remove_admin(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    resp = client.post("/api/users/remove", json={"username": "admin"})
    assert resp.status_code == 400


def test_non_admin_cannot_manage_users(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    client.post("/api/users/add", json={"username": "eve", "password": "test"})
    client.post("/api/logout")
    client.post("/api/login", json={"username": "eve", "password": "test"})
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users/add", json={"username": "hack", "password": "x"}).status_code == 403


def test_regular_user_login(client):
    client.post("/api/login", json={"username": "admin", "password": "test123"})
    client.post("/api/users/add", json={"username": "frank", "password": "mypass"})
    client.post("/api/logout")
    resp = client.post("/api/login", json={"username": "frank", "password": "mypass"})
    assert resp.status_code == 200
    assert resp.get_json()["is_admin"] is False
