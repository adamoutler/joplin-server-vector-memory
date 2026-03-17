import pytest
import subprocess
import time
import requests
import os
import json

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.auth.yml'))

@pytest.fixture(scope="module")
def setup_container():
    # Down first
    subprocess.run(["docker", "compose", "-p", "joplin-test-auth", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
    
    # Run container WITHOUT env vars (no JOPLIN_PASSWORD etc)
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)

    subprocess.run(["docker", "compose", "-p", "joplin-test-auth", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build"], env=env, check=True)
    
    # Wait for the app container to be ready
    ready = False
    for _ in range(30):
        try:
            resp = requests.get("http://localhost:3002/", auth=("setup", "1-mcp-server"))
            if resp.status_code == 200:
                ready = True
                break
        except Exception as e:
            print(f"Connection attempt failed: {e}")
        time.sleep(1)

    if not ready:
        subprocess.run(["docker", "compose", "-p", "joplin-test-auth", "-f", DOCKER_COMPOSE_FILE, "logs", "app"])
        subprocess.run(["docker", "compose", "-p", "joplin-test-auth", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
        pytest.fail("App container did not start in time")
        
    # Wait for joplin server to be ready
    ready = False
    for _ in range(60):
        try:
            resp = requests.get("http://localhost:22301/api/ping")
            if resp.status_code == 200:
                ready = True
                break
        except Exception as e:
            print(f"Connection attempt failed: {e}")
        time.sleep(1)
        
    if not ready:
        pytest.fail("Joplin container did not start in time")
        
    yield "http://localhost:3002"
    
    subprocess.run(["docker", "compose", "-p", "joplin-test-auth", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])

def test_auth_marriage_and_wipe(setup_container):
    base_url = setup_container
    
    # 1. Test accessing without auth
    resp = requests.get(f"{base_url}/")
    assert resp.status_code == 401
    
    # 2. Test accessing with wrong default auth
    resp = requests.get(f"{base_url}/", auth=("admin", "admin"))
    assert resp.status_code == 401
    
    # 3. Test accessing with correct setup auth
    setup_auth = ("setup", "1-mcp-server")
    resp = requests.get(f"{base_url}/", auth=setup_auth)
    assert resp.status_code == 200
    
    # 4. Perform account "marriage" (requires joplin test server to be running)
    # We will point it to the local ephemeral joplin server which runs on port 22300 in the test compose
    joplin_url = "http://joplin:22300"
    real_auth = ("admin@localhost", "admin")
    
    # The POST /auth endpoint does not require basic auth because it's handling the initial config save
    # Wait, the proxy middleware might intercept it! Let's check if POST /auth is authenticated.
    # We should send the setup auth headers.
    resp = requests.post(f"{base_url}/auth", json={
        "serverUrl": joplin_url,
        "username": real_auth[0],
        "password": real_auth[1]
    }, auth=setup_auth)
    
    assert resp.status_code == 200, f"Auth failed: {resp.text}"
    data = resp.json()
    assert data.get("requireRelogin") is True
    assert "locked" in data.get("message", "").lower()
    
    # Wait for the file to be saved and sync to start
    time.sleep(2)
    
    # 5. Verify setup auth is now REJECTED
    resp = requests.get(f"{base_url}/", auth=setup_auth)
    assert resp.status_code == 401
    
    # 6. Verify real auth is now ACCEPTED
    resp = requests.get(f"{base_url}/", auth=real_auth)
    assert resp.status_code == 200
    
    # 7. Use the python API proxy (which internally uses node proxy) to confirm it works
    # This might take a second to initialize the sync client, so we retry.
    for _ in range(10):
        resp = requests.post(f"{base_url}/node-api/notes", json={
            "title": "Auth Lock Test Note",
            "body": "It works after marriage!"
        }, auth=real_auth)
        if resp.status_code == 200:
            break
        time.sleep(1)
        
    assert resp.status_code == 200, f"Node API Notes failed: {resp.text}"
    note_id = resp.json().get("id")
    assert note_id is not None
    
    # 8. Trigger Factory Reset
    resp = requests.post(f"{base_url}/auth/wipe", auth=real_auth)
    assert resp.status_code == 200
    assert resp.json().get("success") is True
    
    # 9. Wait for restart
    time.sleep(5)
    
    # 10. Verify real auth is REJECTED
    resp = requests.get(f"{base_url}/", auth=real_auth)
    assert resp.status_code == 401
    
    # 11. Verify setup auth is ACCEPTED again
    resp = requests.get(f"{base_url}/", auth=setup_auth)
    assert resp.status_code == 200