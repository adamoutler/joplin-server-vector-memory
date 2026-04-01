from src.main import app
import pytest
import os
import sys
import tempfile
import json
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def temp_config_and_db():
    fd_db, db_path = tempfile.mkstemp()
    os.environ["SQLITE_DB_PATH"] = db_path

    fd_conf, conf_path = tempfile.mkstemp()
    config_data = {"api_keys": [{"key": "test-secret-token", "annotation": "test", "expires_at": None}]}
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
    response = client.post("/http-api/search", json={"query": "test"})
    assert response.status_code == 401

    # Test with wrong token
    response = client.post("/http-api/search", json={"query": "test"}, headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_negative_friction_search(client, temp_config_and_db, mock_ollama):
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # Insert multiple notes so we get multiple results
    client.post("/http-api/remember", json={"title": "Apple Recipe 1",
                "content": "How to make apple pie 1. " * 100}, headers=headers)
    client.post("/http-api/remember", json={"title": "Apple Recipe 2",
                "content": "How to make apple pie 2. " * 100}, headers=headers)
    client.post("/http-api/remember", json={"title": "Apple Recipe 3",
                "content": "How to make apple pie 3. " * 100}, headers=headers)

    # Search for apple to get multiple results
    response = client.post("/http-api/search", json={"query": "apple"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3

    # The top ranked result (index 0) should have full_body
    assert "full_body" in data[0]
    assert data[0]["full_body"] is not None
    assert "blurb" in data[0]

    # The other results should NOT have full_body
    for i in range(1, len(data)):
        assert "full_body" not in data[i] or data[i]["full_body"] is None
        assert "blurb" in data[i]


def test_authorized_flow(client, temp_config_and_db, mock_ollama):
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Remember
    response = client.post("/http-api/remember", json={"title": "Apple Recipe",
                           "content": "How to make apple pie"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    note_id = data.get("id")
    assert note_id is not None

    # 2. Get
    response = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("id") == note_id
    assert data.get("title") == "Apple Recipe"
    assert data.get("content") == "How to make apple pie"
    updated_time = data.get("updated_time")

    # 3. Update
    update_req = {
        "note_id": note_id,
        "content": " with cinnamon",
        "update_mode": "append",
        "last_modified_timestamp": updated_time,
        "summary_of_changes": "Added cinnamon"
    }
    response = client.post("/http-api/update", json=update_req, headers=headers)
    assert response.status_code == 200
    assert response.json().get("status") == "success"

    # Verify update
    response = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
    assert response.status_code == 200
    assert response.json().get("content") == "How to make apple pie\n\n with cinnamon"

    # 4. Search
    response = client.post("/http-api/search", json={"query": "apple"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0].get("id") == note_id

    # 5. Delete (2-step friction process)
    # Step 1: Request Deletion
    response = client.post("/http-api/request-deletion",
                           json={"note_id": note_id, "reason": "Test cleanup"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "deletion_token" in data
    deletion_token = data["deletion_token"]
    confirm_title = data.get("confirm_title")

    # Step 2: Execute Deletion
    # First get the note to calculate its content hash (simulating client behavior)
    response = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
    assert response.status_code == 200
    content_hash = response.json().get("content_hash")

    attestation = {
        "content_hash": content_hash,
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }

    response = client.post("/http-api/execute-deletion", json={
        "deletion_token": deletion_token,
        "confirm_title": confirm_title,
        "safety_attestation": attestation
    }, headers=headers)
    if response.status_code != 200:
        print("EXECUTE DELETION ERROR:", response.json())
    assert response.status_code == 200
    assert response.json().get("status") == "success"
    data = response.json()
    assert data.get("status") == "success"

    # Verify deletion
    response = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("error") == "Note not found"


def test_bad_requests(client, temp_config_and_db):
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # Test invalid JSON
    response = client.post("/http-api/search", content="not json", headers=headers)
    assert response.status_code == 422

    # Test missing parameters for each endpoint
    response = client.post("/http-api/search", json={"wrong_key": "apple"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/http-api/get", json={"wrong_key": "123"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/http-api/remember", json={"title": "T"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/http-api/update", json={"wrong_key": "123"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/http-api/request-deletion", json={"wrong_key": "123"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/http-api/execute-deletion", json={"wrong_key": "123"}, headers=headers)
    assert response.status_code == 422


def test_settings_api(client, temp_config_and_db):
    conf_path, db_path, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Get settings
    response = client.get("/api/settings", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "embedding" in data
    assert data["embedding"]["provider"] == "internal"
    assert "chunkSize" in data

    # 2. Update settings (non-critical)
    update_data = data.copy()
    update_data["searchTopK"] = 10

    response = client.post("/api/settings", json=update_data, headers=headers)
    assert response.status_code == 200
    assert response.json()["searchTopK"] == 10

    # Check if saved to file
    with open(conf_path, "r") as f:
        saved_config = json.load(f)
    assert saved_config["searchTopK"] == 10
    # Make sure token was not lost
    assert saved_config["api_keys"][0]["key"] == token

    # 3. Test Polymorphic Embedding Schema via /api/reindex
    # Switch from internal to Ollama
    reindex_data = {
        "embedding": {
            "provider": "ollama",
            "baseUrl": "http://ollama-test:11434",
            "model": "test-model"
        },
        "chunkSize": 3000
    }

    # We need to patch the actual model probe since the server will try to reach out
    with patch("ollama.Client") as mock_ollama:
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": [0.1] * 768}
        mock_ollama.return_value = mock_client

        with patch("src.db.reset_database") as mock_reset:
            # We must mock requests.post to stop it hitting Node proxy during tests
            with patch("requests.post"):
                response = client.post("/api/reindex", json=reindex_data, headers=headers)
                assert response.status_code == 200

                res_data = response.json()
                assert res_data["embedding"]["provider"] == "ollama"
                assert res_data["embedding"]["baseUrl"] == "http://ollama-test:11434"
                assert res_data["embedding"]["model"] == "test-model"
                assert res_data["chunkSize"] == 3000

                with open(conf_path, "r") as f:
                    saved_config = json.load(f)

                # Verify nested structure was flattened or saved perfectly based on how backend handles it
                # Since we changed it to just serialize the nested dict, it should be nested in the JSON file
                assert saved_config["embedding"]["provider"] == "ollama"
                assert saved_config["embedding"]["baseUrl"] == "http://ollama-test:11434"
                assert saved_config["chunkSize"] == 3000

                mock_reset.assert_called_once_with(768)

    # 5. Reset settings
    response = client.post("/api/settings/reset", headers=headers)
    assert response.status_code == 200
    reset_data = response.json()
    # Check default
    assert reset_data["chunkSize"] == 1000
    assert reset_data["searchTopK"] == 5
    assert reset_data["embedding"]["provider"] == "internal"

    with open(conf_path, "r") as f:
        saved_config = json.load(f)
    assert saved_config["chunkSize"] == 1000
    assert saved_config["api_keys"][0]["key"] == token


def test_stateless_mcp_endpoint(temp_config_and_db):
    import subprocess
    import sys
    import time
    import socket
    import requests

    def get_free_port():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port
    port = get_free_port()
    conf_path, db_path, token = temp_config_and_db
    env = os.environ.copy()
    env["SQLITE_DB_PATH"] = db_path
    env["CONFIG_PATH"] = conf_path
    env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        ready = False
        for _ in range(20):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)

        if not ready:
            server_process.terminate()
            stdout, stderr = server_process.communicate()
            pytest.fail(f"Server failed to start. Stdout: {stdout.decode()} \n Stderr: {stderr.decode()}")

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

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # Test 1: no trailing slash, no redirect
        response = requests.post(f"http://127.0.0.1:{port}/http-api/mcp/stateless",
                                 json=request_data, headers=headers, allow_redirects=False)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
        data = response.json()
        assert data.get("jsonrpc") == "2.0"
        assert "result" in data
        assert data["result"]["serverInfo"]["name"] == "JoplinSemanticSearch"

        # Test 2: with trailing slash (if it exists, though Starlette app.api_route might strictly match without slash if we didn't add the path:path parameter, but let's test it)
        # We only explicitly need to ensure that the core mcp endpoint works without throwing 404/307
    finally:
        server_process.terminate()
        server_process.wait()


def test_expired_token(client):
    fd_conf, conf_path = tempfile.mkstemp()
    config_data = {
        "api_keys": [
            {"key": "expired-token", "annotation": "test1", "expires_at": "2020-01-01T00:00:00Z"},
            {"key": "valid-token", "annotation": "test2", "expires_at": "2099-01-01T00:00:00Z"}
        ]
    }
    with open(conf_path, "w") as f:
        json.dump(config_data, f)
    os.environ["CONFIG_PATH"] = conf_path

    # Need to clear cache in main so it re-reads
    import src.main as main_module
    main_module._config_cache = {}
    main_module._config_mtime = 0

    response = client.post("/http-api/search", json={"query": "test"},
                           headers={"Authorization": "Bearer expired-token"})
    assert response.status_code == 401

    response2 = client.post("/http-api/search", json={"query": "test"}, headers={"Authorization": "Bearer valid-token"})
    # It might fail with 500 or something if DB not mocked perfectly, but it should NOT be 401
    assert response2.status_code != 401

    os.close(fd_conf)
    os.remove(conf_path)


def test_maintenance_handshake(client, temp_config_and_db):
    conf_path, db_path, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    update_data = {
        "embedding": {
            "provider": "internal"
        },
        "chunkSize": 3000
    }

    import threading
    import time

    # We will simulate entrypoint.sh creating the confirm file after a delay
    def simulate_entrypoint():
        lock_file = "/tmp/maintenance.lock"
        confirm_file = "/tmp/maintenance.confirm"

        # Wait for Python to create lock file
        for _ in range(30):
            if os.path.exists(lock_file):
                break
            time.sleep(0.1)

        assert os.path.exists(lock_file)

        # Sleep a bit to prove Python is waiting
        time.sleep(1)

        # Write confirm file
        with open(confirm_file, "w") as f:
            f.write("confirm")

    t = threading.Thread(target=simulate_entrypoint)
    t.start()

    with patch("src.db.reset_database") as mock_reset:
        with patch("requests.post"):
            start_time = time.time()
            response = client.post("/api/reindex", json=update_data, headers=headers)
            end_time = time.time()

            assert response.status_code == 200

            # Should have taken at least 1 second since we sleep(1) in the thread
            assert end_time - start_time >= 1.0

    t.join()

    # Assert lock and confirm files are cleaned up
    assert not os.path.exists("/tmp/maintenance.lock")
    assert not os.path.exists("/tmp/maintenance.confirm")


def test_mcp_notes_search(client, temp_config_and_db, mock_ollama):
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # Insert notes to test FTS AND matching
    # Note 1 has both words but NOT explicitly adjacent
    client.post("/http-api/remember", json={"title": "Protocol Doc",
                "content": "This is a document about Samsung. It mentions SIPC later on."}, headers=headers)
    
    # Note 2 has only one word
    client.post("/http-api/remember", json={"title": "TV Guide",
                "content": "This is a document about Samsung TVs."}, headers=headers)
                
    # Note 3 is just filler to test limits
    for i in range(25):
        client.post("/http-api/remember", json={"title": f"Filler {i}",
                    "content": f"Filler content {i}"}, headers=headers)

    # Instead of hanging TestClient over ASGI submounts, call the underlying function!
    from src.main import search_notes
    
    # Search for "samsung SIPC". The tool should parse it to ("samsung" "SIPC") and apply Limit=5
    results = search_notes("samsung SIPC", page=1, limit=5, alpha=0.5, target_date=None, date_weight=0.0, folder=None, recursive=False)
    
    # test limit
    assert len(results) == 5
    
    # Check if our target document is found
    titles = [item["title"] for item in results]
    assert any("Protocol" in t for t in titles)
