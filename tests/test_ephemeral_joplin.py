import subprocess
import time
import requests
import pytest
import os

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docker-compose.test.yml"))

@pytest.fixture(scope="module", autouse=True)
def ephemeral_joplin():
    env = os.environ.copy()
    env["JOPLIN_SERVER_URL"] = "http://joplin:22300"
    env["JOPLIN_USERNAME"] = "admin@localhost"
    env["JOPLIN_PASSWORD"] = "admin"
    env["JOPLIN_MASTER_PASSWORD"] = "admin"

    # Down first just in case
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env)
    # Spin up
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "up", "-d"], env=env, check=True)
    
    # Wait for the server to be ready
    max_retries = 60
    ready = False
    for i in range(max_retries):
        try:
            resp = requests.get("http://localhost:22300/api/ping")
            if resp.status_code == 200:
                ready = True
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
        
    if not ready:
        subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "logs"])
        subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
        raise RuntimeError("Joplin server did not start in time")
        
    os.environ["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    os.environ["JOPLIN_ADMIN_PASSWORD"] = "admin"
    os.environ["JOPLIN_BASE_URL"] = "http://localhost:22300"
    
    try:
        yield
    finally:
        # Tear down
        subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "down", "-v"], check=True)

def test_joplin_is_running():
    resp = requests.get("http://localhost:22300/api/ping")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"

def test_admin_login():
    resp = requests.post("http://localhost:22300/api/sessions", json={
        "email": "admin@localhost",
        "password": "admin"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
