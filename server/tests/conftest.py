import pytest
import subprocess
import time
import requests
import os

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'docker-compose.test.yml'))

@pytest.fixture(scope="session", autouse=True)
def ephemeral_joplin():
    # Ensure no local .env variables leak into the ephemeral environment
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)

    # Down first just in case
    subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env, check=False)
    # Spin up
    subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build"], env=env, check=True)
    
    # Wait for the server to be ready
    max_retries = 30
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
        subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "logs"], env=env)
        subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env, check=False)
        raise RuntimeError("Joplin server did not start in time")
    
    # Provide admin credentials to the test environment
    os.environ["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    os.environ["JOPLIN_ADMIN_PASSWORD"] = "admin"
    os.environ["JOPLIN_BASE_URL"] = "http://localhost:22300"
    
    try:
        yield
    finally:
        # Tear down
        subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env, check=True)
