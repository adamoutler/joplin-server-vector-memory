from src.main import app
import pytest
import os
import sys
import tempfile
import json
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


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

    os.close(fd_db)
    os.remove(db_path)
    os.close(fd_conf)
    os.remove(conf_path)


@pytest.fixture
def mock_ollama():
    with patch("src.main.get_embedding") as mock_embed:

        def side_effect(text):
            vec = [0.0] * 384
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
    response = client.post(
        "/http-api/search",
        json={"query": "test"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_negative_friction_search(client, temp_config_and_db, mock_ollama):
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # Insert multiple notes so we get multiple results
    client.post(
        "/http-api/remember",
        json={"title": "Apple Recipe 1", "content": "How to make apple pie 1. " * 100},
        headers=headers,
    )
    client.post(
        "/http-api/remember",
        json={"title": "Apple Recipe 2", "content": "How to make apple pie 2. " * 100},
        headers=headers,
    )
    client.post(
        "/http-api/remember",
        json={"title": "Apple Recipe 3", "content": "How to make apple pie 3. " * 100},
        headers=headers,
    )

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
    response = client.post(
        "/http-api/remember",
        json={"title": "Apple Recipe", "content": "How to make apple pie"},
        headers=headers,
    )
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
        "summary_of_changes": "Added cinnamon",
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
    response = client.post(
        "/http-api/request-deletion",
        json={"note_id": note_id, "reason": "Test cleanup"},
        headers=headers,
    )
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
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered.",
    }

    response = client.post(
        "/http-api/execute-deletion",
        json={
            "deletion_token": deletion_token,
            "confirm_title": confirm_title,
            "safety_attestation": attestation,
        },
        headers=headers,
    )
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
    response = client.post(
        "/http-api/search", json={"wrong_key": "apple"}, headers=headers
    )
    assert response.status_code == 422

    response = client.post("/http-api/get", json={"wrong_key": "123"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/http-api/remember", json={"title": "T"}, headers=headers)
    assert response.status_code == 422

    response = client.post(
        "/http-api/update", json={"wrong_key": "123"}, headers=headers
    )
    assert response.status_code == 422

    response = client.post(
        "/http-api/request-deletion", json={"wrong_key": "123"}, headers=headers
    )
    assert response.status_code == 422

    response = client.post(
        "/http-api/execute-deletion", json={"wrong_key": "123"}, headers=headers
    )
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
            "model": "test-model",
        },
        "chunkSize": 3000,
    }

    # We need to patch the actual model probe since the server will try to reach out
    with patch("ollama.Client") as mock_ollama:
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": [0.1] * 384}
        mock_ollama.return_value = mock_client

        with patch("src.db.reset_database") as mock_reset:
            # We must mock requests.post to stop it hitting Node proxy during tests
            with patch("requests.post"):
                response = client.post(
                    "/api/reindex", json=reindex_data, headers=headers
                )
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
                assert (
                    saved_config["embedding"]["baseUrl"] == "http://ollama-test:11434"
                )
                assert saved_config["chunkSize"] == 3000

                mock_reset.assert_called_once_with(384)

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
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    port = get_free_port()
    conf_path, db_path, token = temp_config_and_db
    env = os.environ.copy()
    env["SQLITE_DB_PATH"] = db_path
    env["CONFIG_PATH"] = conf_path
    env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    server_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
            pytest.fail(
                f"Server failed to start. Stdout: {stdout.decode()} \n Stderr: {stderr.decode()}"
            )

        request_data = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
            "id": 1,
        }

        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}

        # Test 1: no trailing slash, no redirect
        response = requests.post(
            f"http://127.0.0.1:{port}/http-api/mcp/stateless",
            json=request_data,
            headers=headers,
            allow_redirects=False,
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Response: {response.text}"
        )
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
            {
                "key": "expired-token",
                "annotation": "test1",
                "expires_at": "2020-01-01T00:00:00Z",
            },
            {
                "key": "valid-token",
                "annotation": "test2",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        ]
    }
    with open(conf_path, "w") as f:
        json.dump(config_data, f)
    os.environ["CONFIG_PATH"] = conf_path

    # Need to clear cache in main so it re-reads
    import src.main as main_module

    main_module._config_cache = {}
    main_module._config_mtime = 0

    response = client.post(
        "/http-api/search",
        json={"query": "test"},
        headers={"Authorization": "Bearer expired-token"},
    )
    assert response.status_code == 401

    response2 = client.post(
        "/http-api/search",
        json={"query": "test"},
        headers={"Authorization": "Bearer valid-token"},
    )
    # It might fail with 500 or something if DB not mocked perfectly, but it should NOT be 401
    assert response2.status_code != 401

    os.close(fd_conf)
    os.remove(conf_path)


def test_maintenance_handshake(client, temp_config_and_db):
    conf_path, db_path, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    update_data = {"embedding": {"provider": "internal"}, "chunkSize": 3000}

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

    with patch("src.db.reset_database"):
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
    client.post(
        "/http-api/remember",
        json={
            "title": "Protocol Doc",
            "content": "This is a document about Samsung. It mentions SIPC later on.",
        },
        headers=headers,
    )

    # Note 2 has only one word
    client.post(
        "/http-api/remember",
        json={"title": "TV Guide", "content": "This is a document about Samsung TVs."},
        headers=headers,
    )

    # Note 3 is just filler to test limits
    for i in range(25):
        client.post(
            "/http-api/remember",
            json={"title": f"Filler {i}", "content": f"Filler content {i}"},
            headers=headers,
        )

    # Instead of hanging TestClient over ASGI submounts, call the underlying function!
    from src.main import search_notes, extract_result

    # Search for "samsung SIPC". The tool should parse it to ("samsung" "SIPC") and apply Limit=5
    results = extract_result(
        search_notes(
            "samsung SIPC",
            page=1,
            limit=5,
            alpha=0.5,
            target_date=None,
            date_weight=0.0,
            folder=None,
            recursive=False,
        )
    )

    # test limit
    assert len(results) == 5

    # Check if our target document is found
    titles = [item["title"] for item in results]
    assert any("Protocol" in t for t in titles)


def test_get_embedding_dimension_mock():
    from src.main import _get_embedding_dimension
    from fastapi import HTTPException

    # Should default to 384
    assert _get_embedding_dimension({}) == 384
    assert _get_embedding_dimension({"provider": "openai"}) == 384

    # Test ollama with exception
    with patch("src.main.ollama.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.embeddings.side_effect = Exception("Network error")
        mock_client_cls.return_value = mock_client

        with pytest.raises(HTTPException):
            _get_embedding_dimension(
                {"provider": "ollama", "baseUrl": "http://mock", "model": "test-model"}
            )

    # Test ollama success
    with patch("src.main.ollama.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": [0.1] * 512}
        mock_client_cls.return_value = mock_client

        dim = _get_embedding_dimension(
            {"provider": "ollama", "baseUrl": "http://mock", "model": "test-model"}
        )
        assert dim == 512


def test_merge_rrf_scores():
    from src.main import _merge_rrf_scores

    exact = [(1, "id1", "title1", "content1", 100, "pid1", "path1")]
    vec = [(2, "id2", "title2", "content2", 0.5, 200, "pid2", "path2")]
    fts = [(3, "id3", "title3", "content3", 0.9, 300, "pid3", "path3")]
    rrf, data = _merge_rrf_scores(exact, vec, fts, 0.5)
    assert 1 in rrf
    assert 2 in rrf
    assert 3 in rrf
    assert rrf[1] == 1000.0  # Exact match boost
    assert rrf[2] > 0
    assert rrf[3] > 0
    assert data[1]["id"] == "id1"


def test_root_endpoint(client):
    """GET / must return 200 with server status message (lines 1600-1608)."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "Joplin Server Vector Memory API is running" in data["message"]


def test_force_accept_json_middleware_unauthorized(client, temp_config_and_db):
    """ForceAcceptJSONMiddleware must immediately return 401 on /mcp or /http-api/mcp when unauthorized (lines 2095-2122)."""
    # 1. No Authorization header to /mcp
    res1 = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert res1.status_code == 401
    assert res1.headers.get("content-type") == "application/json"
    assert res1.headers.get("www-authenticate") == "Bearer"
    assert res1.json() == {"detail": "Unauthorized"}

    # 2. Invalid Bearer token to /mcp
    res2 = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": "Bearer bad-token-xyz"},
    )
    assert res2.status_code == 401
    assert res2.json() == {"detail": "Unauthorized"}

    # 3. No Authorization header to /http-api/mcp
    res3 = client.get("/http-api/mcp")
    assert res3.status_code == 401
    assert res3.json() == {"detail": "Unauthorized"}

    # 4. Non-Bearer authorization header (e.g. Basic)
    res4 = client.post(
        "/mcp",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert res4.status_code == 401


def test_custom_openapi_injections_and_cache():
    """Verify custom_openapi injects 400, 401, 403, 405 responses and caches result (lines 2165-2195)."""
    from src.main import app, custom_openapi

    # Invalidate cache
    app.openapi_schema = None

    schema1 = custom_openapi()
    assert schema1 is not None
    assert "paths" in schema1

    # Verify injected response codes across paths
    for path, methods in schema1["paths"].items():
        for method, details in methods.items():
            responses = details.get("responses", {})
            assert "400" in responses
            assert "401" in responses
            assert "403" in responses
            assert "405" in responses

    # Verify JsonRpcRequest components
    assert "JsonRpcRequest" in schema1["components"]["schemas"]

    # Verify line 2166 cache hit branch
    schema2 = custom_openapi()
    assert schema2 is schema1


def test_test_model_endpoint_local_fallback(client, temp_config_and_db):
    """Empty baseUrl in /api/settings/test-model returns 384 local dimension (lines 1873-1874)."""
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/settings/test-model",
        json={"baseUrl": "", "model": "any-local-model"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "dimension": 384}


def test_test_model_endpoint_ollama_success_and_pull(client, temp_config_and_db):
    """Test Ollama client show success vs pull fallback (lines 1875-1886)."""
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # Case 1: Model exists locally (show succeeds)
    with patch("ollama.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.show.return_value = {"status": "ok"}
        mock_client.embeddings.return_value = {"embedding": [0.0] * 768}
        mock_client_cls.return_value = mock_client

        response = client.post(
            "/api/settings/test-model",
            json={"baseUrl": "http://mock-ollama:11434", "model": "test-embed"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "dimension": 768}
        mock_client.pull.assert_not_called()

    # Case 2: Model not found locally (show raises, pull succeeds)
    with patch("ollama.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.show.side_effect = Exception("Model not found")
        mock_client.pull.return_value = {"status": "downloaded"}
        mock_client.embeddings.return_value = {"embedding": [0.0] * 1024}
        mock_client_cls.return_value = mock_client

        response = client.post(
            "/api/settings/test-model",
            json={"baseUrl": "http://mock-ollama:11434", "model": "pull-model"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "dimension": 1024}
        mock_client.pull.assert_called_once_with("pull-model")


def test_test_model_endpoint_failures(client, temp_config_and_db):
    """Test failure branches: missing embedding field, connection error, and 401 (lines 1886-1893)."""
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Unauthenticated request
    unauth_resp = client.post(
        "/api/settings/test-model",
        json={"baseUrl": "http://mock:11434", "model": "test"},
    )
    assert unauth_resp.status_code == 401

    # 2. Response without "embedding" key
    with patch("ollama.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"other": "no-embedding"}
        mock_client_cls.return_value = mock_client

        res = client.post(
            "/api/settings/test-model",
            json={"baseUrl": "http://mock:11434", "model": "test"},
            headers=headers,
        )
        assert res.status_code == 400
        assert "Failed to connect to or pull the specified model" in res.json()["detail"]

    # 3. Connection/network error
    with patch("ollama.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.embeddings.side_effect = ConnectionError("Connection refused")
        mock_client_cls.return_value = mock_client

        res2 = client.post(
            "/api/settings/test-model",
            json={"baseUrl": "http://mock:11434", "model": "test"},
            headers=headers,
        )
        assert res2.status_code == 400


def test_update_note_validation_and_errors(client, temp_config_and_db, mock_ollama):
    """Comprehensive test of note update validation edge cases (lines 985-1092)."""
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a baseline note to test updates against
    rem_resp = client.post(
        "/http-api/remember",
        json={"title": "Test Update Note", "content": "Initial sentence. Target phrase here. End sentence."},
        headers=headers,
    )
    assert rem_resp.status_code == 200
    note_id = rem_resp.json()["id"]

    # Fetch note to get current updated_time
    get_resp = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
    assert get_resp.status_code == 200
    current_time = get_resp.json()["updated_time"]

    # 2. Note not found -> 404 (line 986)
    res_not_found = client.post(
        "/http-api/update",
        json={
            "note_id": "non-existent-id-999",
            "content": "abc",
            "update_mode": "append",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_not_found.status_code == 404
    assert res_not_found.json()["detail"] == "Note not found"

    # 3. Concurrency timestamp mismatch -> 409 (line 993)
    res_occ = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "abc",
            "update_mode": "append",
            "last_modified_timestamp": current_time - 500,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_occ.status_code == 409
    assert "modified since you last read it" in res_occ.json()["detail"]

    # 4. Payload size limit >= 1_000_000 characters -> 400 (lines 998-1000)
    res_large_content = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "X" * 1_000_001,
            "update_mode": "append",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_large_content.status_code == 400
    assert res_large_content.json()["detail"] == "replace text too long"

    res_large_search = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "new",
            "search_text": "Y" * 1_000_001,
            "update_mode": "partial note replacement",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_large_search.status_code == 400
    assert res_large_search.json()["detail"] == "replace text too long"

    # 5. search_text used with append or prepend -> 400 (line 1008)
    res_append_search = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "abc",
            "search_text": "Target phrase",
            "update_mode": "append",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_append_search.status_code == 400
    assert "search_text cannot be used with append or prepend" in res_append_search.json()["detail"]

    # 6. Partial mode without search_text or empty search_text -> 400 (lines 1012, 1017)
    res_empty_search = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "abc",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_empty_search.status_code == 400
    assert "search text cannot be empty" in res_empty_search.json()["detail"]

    # 7. search_text not found -> 400 (line 1022)
    res_search_not_found = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "Replacement text",
            "search_text": "Non-existent phrase",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_search_not_found.status_code == 400
    assert res_search_not_found.json()["detail"] == "search text not found"

    # 8. Duplicate search_text matches: short <= 200 chars vs long > 200 chars truncation (line 1028)
    # First update note to contain duplicate short words
    client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "word word word",
            "update_mode": "full note replacement",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "reset",
        },
        headers=headers,
    )
    current_time = client.post("/http-api/get", json={"note_id": note_id}, headers=headers).json()["updated_time"]

    res_dup_short = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "replacement",
            "search_text": "word",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_dup_short.status_code == 400
    assert "multiple instances of `word` found" in res_dup_short.json()["detail"]

    # Duplicate long search_text (> 200 chars) to test truncation display (line 1027)
    long_dup_str = "Z" * 210
    client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": f"{long_dup_str} middle {long_dup_str}",
            "update_mode": "full note replacement",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "reset long",
        },
        headers=headers,
    )
    current_time = client.post("/http-api/get", json={"note_id": note_id}, headers=headers).json()["updated_time"]

    res_dup_long = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "replacement",
            "search_text": long_dup_str,
            "update_mode": "partial note replacement",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "test",
        },
        headers=headers,
    )
    assert res_dup_long.status_code == 400
    expected_truncated = "Z" * 197 + "..."
    assert f"multiple instances of `{expected_truncated}` found" in res_dup_long.json()["detail"]

    # 9. Invalid update_mode (tested directly via update_note function) (line 1044)
    from src.main import update_note, extract_result
    raw_invalid_mode_res = extract_result(
        update_note(
            note_id=note_id,
            content="abc",
            update_mode="unsupported_custom_mode",
            last_modified_timestamp=current_time,
        )
    )
    assert "Invalid update_mode" in raw_invalid_mode_res["error"]

    # 10. Joplin node proxy relay failure -> returns error (line 1056)
    with patch("src.main._call_node_proxy") as mock_proxy:
        fail_resp = MagicMock()
        fail_resp.status_code = 502
        fail_resp.text = "Bad Gateway to Joplin"
        mock_proxy.return_value = fail_resp

        res_joplin_fail = client.post(
            "/http-api/update",
            json={
                "note_id": note_id,
                "content": "abc",
                "update_mode": "full note replacement",
                "last_modified_timestamp": current_time,
                "summary_of_changes": "test",
            },
            headers=headers,
        )
        assert res_joplin_fail.status_code == 400
        assert "Failed to update note in Joplin: Bad Gateway to Joplin" in res_joplin_fail.json()["detail"]

    # 11. Joplin relay exception triggers db.rollback() (lines 1087-1091)
    with patch("src.main._call_node_proxy") as mock_proxy:
        mock_proxy.side_effect = RuntimeError("Proxy write socket closed abruptly")
        res_proxy_exc = client.post(
            "/http-api/update",
            json={
                "note_id": note_id,
                "content": "abc",
                "update_mode": "full note replacement",
                "last_modified_timestamp": current_time,
                "summary_of_changes": "test",
            },
            headers=headers,
        )
        assert res_proxy_exc.status_code == 400
        assert "Proxy write socket closed abruptly" in res_proxy_exc.json()["detail"]

    # 12. Successful Prepend and Partial Replacement updates
    # Prepend
    res_prepend = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "Header Note Line",
            "update_mode": "prepend",
            "last_modified_timestamp": current_time,
            "summary_of_changes": "prepend test",
        },
        headers=headers,
    )
    assert res_prepend.status_code == 200
    get_prep = client.post("/http-api/get", json={"note_id": note_id}, headers=headers).json()
    assert get_prep["content"].startswith("Header Note Line\n\n")

    # Partial replace
    new_time = get_prep["updated_time"]
    res_partial = client.post(
        "/http-api/update",
        json={
            "note_id": note_id,
            "content": "Replaced Line",
            "search_text": "Header Note Line",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": new_time,
            "summary_of_changes": "partial test",
        },
        headers=headers,
    )
    assert res_partial.status_code == 200
    get_part = client.post("/http-api/get", json={"note_id": note_id}, headers=headers).json()
    assert "Replaced Line" in get_part["content"]
    assert "Header Note Line" not in get_part["content"]
