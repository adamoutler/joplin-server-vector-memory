import pytest
import os
import uuid
from unittest.mock import patch, MagicMock

import src.main

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'docker-compose.test.yml'))


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Ensure src.main._config_cache is cleared between tests."""
    src.main._config_cache = {}
    src.main._config_mtime = 0
    yield
    src.main._config_cache = {}
    src.main._config_mtime = 0


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
