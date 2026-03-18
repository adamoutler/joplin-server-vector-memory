import pytest
import requests
import time
import os
import sys
import subprocess

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.test.yml'))

@pytest.fixture(scope="module")
def setup_live_container_unhappy():
    print("\n[setup_live_container_unhappy] Tearing down any existing containers...", file=sys.stderr)
    subprocess.run(["docker", "compose", "-p", "joplin-unhappy-e2e", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
    
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)
    
    env["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    env["JOPLIN_ADMIN_PASSWORD"] = "admin"
    env["JOPLIN_BASE_URL"] = "http://localhost:22300"

    print("[setup_live_container_unhappy] Starting joplin-unhappy-e2e cluster...", file=sys.stderr)
    subprocess.run(["docker", "compose", "-p", "joplin-unhappy-e2e", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build"], env=env, check=True)
    
    # Wait for the app container to be ready in setup mode
    ready = False
    for _ in range(30):
        try:
            resp = requests.get("http://localhost:3001/", auth=("setup", "1-mcp-server"), timeout=30)
            if resp.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)

    if not ready:
        subprocess.run(["docker", "compose", "-p", "joplin-unhappy-e2e", "-f", DOCKER_COMPOSE_FILE, "logs", "app"])
        subprocess.run(["docker", "compose", "-p", "joplin-unhappy-e2e", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
        pytest.fail("App container did not start in time")
        
    yield
    
    subprocess.run(["docker", "compose", "-p", "joplin-unhappy-e2e", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])

@pytest.mark.enable_socket
def test_sync_fails_with_bad_credentials(setup_live_container_unhappy):
    PROXY_URL = "http://localhost:3001"

    # Configure the app with a bad password
    auth_payload = {
        "serverUrl": "http://joplin:22300", 
        "username": "admin@localhost",
        "password": "wrong_password",
        "masterPassword": "test_master_password",
        "rotate": True
    }
    
    # The /auth endpoint should now immediately test the credentials and reject them
    auth_resp = requests.post(f"{PROXY_URL}/auth", json=auth_payload, auth=("setup", "1-mcp-server"), timeout=30)
    assert auth_resp.status_code in [400, 403], f"Expected /auth to reject bad credentials, got {auth_resp.status_code}: {auth_resp.text}"
    
    auth_data = auth_resp.json()
    assert "Invalid username or password" in auth_data.get("error", "") or "Authentication failed" in auth_data.get("error", ""), "Expected specific error message"
