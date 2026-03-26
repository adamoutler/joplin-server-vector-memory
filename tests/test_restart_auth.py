import pytest
import requests
import subprocess
import time
from playwright.sync_api import sync_playwright

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
        "password": "admin",
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
    # Restart the app container 1st time
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "restart", "app"], check=True)
    
    # Wait for the HTTP port to be open, but don't loop on status code
    time.sleep(3)
    
    r = requests.get(f"{proxy_url}/", auth=("admin@localhost", "admin"))
    assert r.status_code == 200, f"Expected 200 after 1st restart, got {r.status_code}. Body: {r.text}"
    
    # Restart the app container 2nd time
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "restart", "app"], check=True)
    
    time.sleep(3)
    
    r = requests.get(f"{proxy_url}/", auth=("admin@localhost", "admin"))
    assert r.status_code == 200, f"Expected 200 after 2nd restart, got {r.status_code}. Body: {r.text}"
