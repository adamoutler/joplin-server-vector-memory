from src.main import get_config
import os
import json
import pytest
from unittest.mock import patch
import sys

# Ensure src module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def mock_env(tmp_path):
    config_path = tmp_path / "config.json"
    with patch.dict(os.environ, {"CONFIG_PATH": str(config_path)}, clear=True):
        yield config_path


def test_default_config(mock_env):
    config = get_config()
    assert config["ollama_url"] == ""
    assert config["embedding_model"] == "nomic-embed-text"


def test_env_config(mock_env):
    with patch.dict(os.environ, {
        "OLLAMA_URL": "http://env-ollama:11434",
        "EMBEDDING_MODEL": "env-model",
        "CONFIG_PATH": str(mock_env)
    }):
        config = get_config()
        assert config["ollama_url"] == "http://env-ollama:11434"
        assert config["embedding_model"] == "env-model"


def test_file_config(mock_env):
    # Set env vars
    with patch.dict(os.environ, {
        "OLLAMA_URL": "http://env-ollama:11434",
        "EMBEDDING_MODEL": "env-model",
        "CONFIG_PATH": str(mock_env)
    }):
        # Write config file which should take precedence
        with open(mock_env, "w") as f:
            json.dump({
                "ollamaUrl": "http://file-ollama:11434",
                "embeddingModel": "file-model"
            }, f)

        config = get_config()
        assert config["ollama_url"] == "http://file-ollama:11434"
        assert config["embedding_model"] == "file-model"


def test_file_config_uppercase_keys(mock_env):
    with open(mock_env, "w") as f:
        json.dump({
            "OLLAMA_URL": "http://file-ollama-upper:11434",
            "EMBEDDING_MODEL": "file-model-upper"
        }, f)

    config = get_config()
    assert config["ollama_url"] == "http://file-ollama-upper:11434"
    assert config["embedding_model"] == "file-model-upper"
