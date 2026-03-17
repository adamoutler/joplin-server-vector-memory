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


@pytest.fixture(scope="session")
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
    # Spin up and wait for healthchecks
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null",
                   "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build", "--wait"], env=env, check=True)

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
