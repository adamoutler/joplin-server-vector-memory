import pytest
import os
import sys
import tempfile
import json
from unittest.mock import patch
from starlette.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.main import app

@pytest.fixture
def temp_config_and_db():
    fd_db, db_path = tempfile.mkstemp()
    os.environ["SQLITE_DB_PATH"] = db_path

    fd_conf, conf_path = tempfile.mkstemp()
    config_data = {"token": "test-secret-token"}
    with open(conf_path, "w") as f:
        json.dump(config_data, f)
    os.environ["CONFIG_PATH"] = conf_path

    yield conf_path, db_path, "test-secret-token"

    os.close(fd_db)
    os.remove(db_path)
    os.close(fd_conf)
    os.remove(conf_path)

@pytest.fixture
def mock_ollama():
    with patch('src.main.get_embedding') as mock_embed:
        def side_effect(text):
            vec = [0.0] * 768
            if "test query" in text.lower():
                vec[0] = 1.0
            elif "apple" in text.lower():
                vec[1] = 1.0
            else:
                vec[2] = 1.0
            return vec
        mock_embed.side_effect = side_effect
        yield mock_embed

@pytest.fixture
def client():
    return TestClient(app)

def test_unauthorized(client, temp_config_and_db):
    # Test without header
    response = client.post("/api/search", json={"query": "test"})
    assert response.status_code == 401
    
    # Test with wrong token
    response = client.post("/api/search", json={"query": "test"}, headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401

def test_authorized_flow(client, temp_config_and_db, mock_ollama):
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Remember
    response = client.post("/api/remember", json={"title": "Apple Recipe", "content": "How to make apple pie"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    note_id = data.get("id")
    assert note_id is not None
    
    # 2. Get
    response = client.post("/api/get", json={"note_id": note_id}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("id") == note_id
    assert data.get("title") == "[Agent Memory] Apple Recipe"
    assert data.get("content") == "How to make apple pie"
    
    # 3. Search
    response = client.post("/api/search", json={"query": "apple"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0].get("id") == note_id
    
    # 4. Delete
    response = client.post("/api/delete", json={"note_id": note_id}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    
    # Verify deletion
    response = client.post("/api/get", json={"note_id": note_id}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("error") == "Note not found"

def test_bad_requests(client, temp_config_and_db):
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test invalid JSON
    response = client.post("/api/search", content="not json", headers=headers)
    assert response.status_code == 422
    
    # Test missing parameters for each endpoint
    response = client.post("/api/search", json={"wrong_key": "apple"}, headers=headers)
    assert response.status_code == 422
    
    response = client.post("/api/get", json={"wrong_key": "123"}, headers=headers)
    assert response.status_code == 422
    
    response = client.post("/api/remember", json={"title": "T"}, headers=headers)
    assert response.status_code == 422
    
    response = client.post("/api/delete", json={"wrong_key": "123"}, headers=headers)
    assert response.status_code == 422

def test_stateless_mcp_endpoint():
    from src.main import app
    from fastapi.testclient import TestClient
    
    # We must use TestClient in a context manager to trigger lifespan events
    # which initializes the FastMCP task groups
    with TestClient(app) as client:
        # Test that the stateless endpoint accepts standard POST JSON-RPC requests
        request_data = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            },
            "id": 1
        }
        
        # We must provide the correct Accept header for json_response=True in FastMCP stateless
        headers = {"Accept": "application/json"}
        
        response = client.post("/mcp-server/stateless", json=request_data, headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("jsonrpc") == "2.0"
        assert "result" in data
        assert data["result"]["serverInfo"]["name"] == "JoplinSemanticSearch"


