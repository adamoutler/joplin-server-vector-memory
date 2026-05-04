import pytest
import requests
import subprocess
import time
import os


@pytest.mark.enable_socket
def test_redis_credential_caching_on_restart(ephemeral_joplin):
    # Enable the redis profile and REDIS_URL for this specific test
    env = os.environ.copy()
    env["REDIS_URL"] = "redis://:joplin_redis@redis:6379"

    # Start the test environment with redis profile
    subprocess.run(["docker", "compose", "-f", "tests/docker-compose.test.yml", "--profile", "redis", "-p", "joplin-test-env", "up", "-d"], env=env, check=True)
    time.sleep(5)  # give it time to fully initialize

    proxy_url = "http://127.0.0.1:3001"

    # Setup Auth
    setup_payload = {
        "serverUrl": "http://joplin:22300",
        "username": "admin@localhost",
        "password": os.environ.get("JOPLIN_ADMIN_PASSWORD", "admin"),
        "masterPassword": "admin",
        "memoryServerAddress": "http://localhost:8000"
    }
    r = requests.post(f"{proxy_url}/auth", json=setup_payload, auth=("setup", "1-mcp-server"))
    assert r.status_code == 200, f"Setup failed: {r.text}"
    time.sleep(2)

    # Verify we can authenticate as the user
    r = requests.get(f"{proxy_url}/status", auth=("admin@localhost", "admin"))
    assert r.status_code == 200

    # Take down the app container (simulating crash or restart)
    subprocess.run(["docker", "compose", "-f", "tests/docker-compose.test.yml", "-p", "joplin-test-env", "stop", "app"], check=True)
    time.sleep(2)

    # Bring app container back up
    subprocess.run(["docker", "compose", "-f", "tests/docker-compose.test.yml", "-p", "joplin-test-env", "start", "app"], check=True)

    # Wait for the node app to come back online
    for _ in range(25):
        try:
            r = requests.get(f"{proxy_url}/status", timeout=2)
            if r.status_code == 200 and r.json().get("hasCredentials") is True:
                break
        except Exception:
            pass
        time.sleep(1)

    r = requests.get(f"{proxy_url}/status", auth=("admin@localhost", "admin"))
    assert r.status_code == 200, "Failed auto-auth after restart with Redis"
    data = r.json()
    assert data.get("hasCredentials") is True, "Credentials not loaded from Redis on startup"

    # Teardown the profile properly
    subprocess.run(["docker", "compose", "-f", "tests/docker-compose.test.yml", "--profile", "redis", "-p", "joplin-test-env", "down"], env=env)
