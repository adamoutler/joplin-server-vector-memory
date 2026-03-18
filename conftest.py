import pytest
import subprocess
import os
import time
import requests

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'docker-compose.test.yml'))

@pytest.fixture(scope="session")
def ephemeral_joplin():
    env = os.environ.copy()
    env["JOPLIN_SERVER_URL"] = "http://joplin:22300"
    env["JOPLIN_USERNAME"] = "admin@localhost"
    env["JOPLIN_PASSWORD"] = "admin"
    env["JOPLIN_MASTER_PASSWORD"] = "admin"

    # Down first just in case
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v", "--remove-orphans"], env=env, check=False)
    
    # Spin up and wait for healthchecks
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build", "--force-recreate", "--remove-orphans", "--wait"], env=env, check=True)
        
    os.environ["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    os.environ["JOPLIN_ADMIN_PASSWORD"] = "admin"
    os.environ["JOPLIN_BASE_URL"] = "http://joplin:22300"
    
    # Poll endpoints to ensure they are actually ready for traffic
    max_retries = 30
    for _ in range(max_retries):
        try:
            # Check Joplin
            resp1 = requests.get("http://joplin:22300/api/ping", timeout=2)
            # Check Node Proxy
            resp2 = requests.get("http://localhost:3001/status", timeout=2)
            # Check FastAPI backend
            resp3 = requests.get("http://localhost:8002/", timeout=2)
            
            if resp1.status_code == 200 and resp2.status_code in [200, 401] and resp3.status_code == 200:
                break
            time.sleep(1)
        except requests.exceptions.ConnectionError:
            time.sleep(1)
            continue
        except requests.exceptions.Timeout:
            time.sleep(1)
            continue
    
    try:
        yield
    finally:
        # Tear down
        subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v", "--remove-orphans"], check=True)
