import pytest
import requests
import subprocess
import time
import os


@pytest.mark.enable_socket
def test_container_restart_keeps_auth(ephemeral_joplin):
    proxy_url = "http://127.0.0.1:3001"

    # Wait for proxy to come up
    max_retries = 30
    for i in range(max_retries):
        try:
            r = requests.get(f"{proxy_url}/status")
            if r.status_code in [401, 200]:
                break
        except Exception:
            pass
        time.sleep(1)

    # Clear config just in case it's lingering
    try:
        requests.post(f"{proxy_url}/auth/wipe", auth=("admin@localhost", "admin"), timeout=5)
        requests.post(f"{proxy_url}/auth/wipe", auth=("setup", "1-mcp-server"), timeout=5)
    except Exception:
        pass

    time.sleep(3)

    # Wait for proxy to come back up after wipe
    for i in range(max_retries):
        try:
            r = requests.get(f"{proxy_url}/status")
            if r.status_code in [401, 200]:
                break
        except Exception:
            pass
        time.sleep(1)

    # Login and configure via API
    setup_payload = {
        "serverUrl": "http://joplin:22300",
        "username": "admin@localhost",
        "password": os.environ["JOPLIN_ADMIN_PASSWORD"],
        "memoryServerAddress": "http://localhost:8000"
    }
    r = requests.post(f"{proxy_url}/auth", json=setup_payload, auth=("setup", "1-mcp-server"))
    if r.status_code != 200:
        logs = subprocess.run(["docker", "compose", "-p", "joplin-test-env", "logs", "app"], capture_output=True, text=True).stdout
        print("DOCKER LOGS:\n", logs)
    assert r.status_code == 200, f"Expected 200 from /auth, got {r.status_code}. Body: {r.text}"
    time.sleep(2)        

    # Verify normal user can log in
    r = requests.get(f"{proxy_url}/", auth=("admin@localhost", "admin"))
    if r.status_code != 200:
        logs = subprocess.run(["docker", "compose", "-p", "joplin-test-env", "logs", "app"], capture_output=True, text=True).stdout
        print("DOCKER LOGS:\n", logs)
    assert r.status_code == 200, f"Expected 200 after initial setup, got {r.status_code}. Body: {r.text}"    

    # --- 1st Restart Sequence ---
    # Take the server down
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "stop", "app"], check=True)

    # Check for a response to ensure it's down
    try:
        requests.get(f"{proxy_url}/status", timeout=2)
        assert False, "Server should be down, but got a response"
    except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
        pass  # Expected

    # Bring the server back up
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "start", "app"], check=True)

    # Wait for the HTTP port to be open and the app to be ready
    for i in range(15):
        try:
            r = requests.get(f"{proxy_url}/", auth=("admin@localhost", "admin"), timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)

    r = requests.get(f"{proxy_url}/", auth=("admin@localhost", "admin"))
    assert r.status_code == 200, f"Expected 200 after 1st restart, got {r.status_code}. Body: {r.text}"

    # --- 2nd Restart Sequence ---
    # Take the server down
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "stop", "app"], check=True)

    # Check for a response to ensure it's down
    try:
        requests.get(f"{proxy_url}/status", timeout=2)
        assert False, "Server should be down, but got a response"
    except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
        pass  # Expected

    # Bring the server back up
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "start", "app"], check=True)

    # Wait for the HTTP port to be open and the app to be ready
    for i in range(15):
        try:
            r = requests.get(f"{proxy_url}/", auth=("admin@localhost", "admin"), timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)

    r = requests.get(f"{proxy_url}/", auth=("admin@localhost", "admin"))
    assert r.status_code == 200, f"Expected 200 after 2nd restart, got {r.status_code}. Body: {r.text}"
