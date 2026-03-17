import pytest
import subprocess
import time
import requests
import os
import uuid
from unittest.mock import patch, MagicMock

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'docker-compose.test.yml'))


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Ensure tests run with a consistent environment to avoid host-dependent failures."""
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")


@pytest.fixture(autouse=True)
def mock_node_proxy():
    with patch('src.main._call_node_proxy') as mock:
        def side_effect(method, path, json_data=None):
            resp = MagicMock()
            resp.status_code = 200
            # Mock the JSON response for remember, update, etc.
            # Usually we need to return an "id" for POST /node-api/notes
            resp.json.return_value = {"id": uuid.uuid4().hex, "status": "success"}
            return resp
        mock.side_effect = side_effect
        yield mock


@pytest.fixture(scope="session", autouse=True)
def ephemeral_joplin():
    # Ensure no local .env variables leak into the ephemeral environment
    env = os.environ.copy()
    env["JOPLIN_SERVER_URL"] = "http://joplin:22300"
    env["JOPLIN_USERNAME"] = "admin@localhost"
    env["JOPLIN_PASSWORD"] = "admin"
    env["JOPLIN_MASTER_PASSWORD"] = "admin"

    # Down first just in case
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null",
                   "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env, check=False)
    # Spin up
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null",
                   "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build"], env=env, check=True)

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
        subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file",
                       "/dev/null", "-f", DOCKER_COMPOSE_FILE, "logs"], env=env)
        subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null",
                       "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env, check=False)
        raise RuntimeError("Joplin server did not start in time")

    # Wait for the app container to be ready
    app_ready = False
    for i in range(max_retries):
        try:
            resp = requests.get("http://localhost:8002/http-api/mcp/stateless", timeout=2)
            # Just getting a response (even 405 Method Not Allowed) means it's up
            app_ready = True
            break
        except requests.exceptions.ConnectionError:
            pass
        except requests.exceptions.ReadTimeout:
            pass
        time.sleep(1)

    if not app_ready:
        subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file",
                       "/dev/null", "-f", DOCKER_COMPOSE_FILE, "logs"], env=env)
        subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null",
                       "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env, check=False)
        raise RuntimeError("App container did not start in time")

    # Provide admin credentials to the test environment
    os.environ["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    os.environ["JOPLIN_ADMIN_PASSWORD"] = "admin"
    os.environ["JOPLIN_BASE_URL"] = "http://localhost:22300"

    try:
        yield
    finally:
        # Tear down
        subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null",
                       "-f", DOCKER_COMPOSE_FILE, "down", "-v"], env=env, check=True)
