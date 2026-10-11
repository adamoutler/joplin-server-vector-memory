import pytest
import os
import sys
import uuid
import tempfile
import json
from unittest.mock import patch, MagicMock

# Ensure src is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

DOCKER_COMPOSE_FILE = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "tests", "docker-compose.test.yml"
    )
)


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Ensure src.main._config_cache is cleared between tests."""
    import src.main

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
    with patch("src.main._call_node_proxy") as mock:

        def side_effect(method, path, json_data=None):
            resp = MagicMock()
            resp.status_code = 200
            # Mock the JSON response for remember, update, etc.
            # Usually we need to return an "id" for POST /node-api/notes
            resp.json.return_value = {"id": uuid.uuid4().hex, "status": "success"}
            return resp

        mock.side_effect = side_effect
        yield mock


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    os.environ["SQLITE_DB_PATH"] = path

    yield path

    try:
        os.close(fd)
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@pytest.fixture
def temp_config_and_db():
    fd_db, db_path = tempfile.mkstemp()
    os.environ["SQLITE_DB_PATH"] = db_path

    fd_conf, conf_path = tempfile.mkstemp()
    config_data = {
        "api_keys": [
            {"key": "test-secret-token", "annotation": "test", "expires_at": None}
        ]
    }
    with open(conf_path, "w") as f:
        json.dump(config_data, f)
    os.environ["CONFIG_PATH"] = conf_path

    yield conf_path, db_path, "test-secret-token"

    try:
        os.close(fd_db)
        if os.path.exists(db_path):
            os.remove(db_path)
    except OSError:
        pass

    try:
        os.close(fd_conf)
        if os.path.exists(conf_path):
            os.remove(conf_path)
    except OSError:
        pass


@pytest.fixture
def mock_ollama():
    with patch("src.main.get_embedding") as mock_embed:

        def side_effect(text):
            vec = [0.0] * 384
            if isinstance(text, str):
                if "test query" in text.lower():
                    vec[0] = 1.0
                elif "apple" in text.lower():
                    vec[1] = 1.0
                else:
                    vec[2] = 1.0
            elif isinstance(text, list):
                return [[0.0] * 384 for _ in text]
            return vec

        mock_embed.side_effect = side_effect
        yield mock_embed
