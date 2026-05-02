import pytest
import requests
import time
import os
import uuid
import sys

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'docker-compose.test.yml'))


@pytest.mark.enable_socket
def test_api_server_live_endpoints(ephemeral_joplin):
    # setup_live_container starts docker-compose.test.yml which exposes:
    # app proxy on 3001
    # app backend on 8002
    PROXY_URL = "http://localhost:3001"
    BACKEND_URL = "http://localhost:8002"

    # Wait for the backend and proxy to be fully responsive
    max_retries = 60
    for i in range(max_retries):
        try:
            r1 = requests.get(f"{BACKEND_URL}/docs", timeout=2)
            r2 = requests.get(f"{PROXY_URL}/docs", timeout=2)
            r3 = requests.get(f"{PROXY_URL}/", timeout=2)
            if r1.status_code in [200, 404] and r2.status_code in [200, 404] and r3.status_code in [200, 401]:
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
            pass
        time.sleep(1)    # Verify that the ports are responding properly
    docs_8000 = requests.get(f"{BACKEND_URL}/docs", timeout=30)
    assert docs_8000.status_code == 200, f"Backend /docs should return 200, got {docs_8000.status_code}"

    docs_3000 = requests.get(f"{PROXY_URL}/docs", timeout=30)
    assert docs_3000.status_code == 200, f"Proxy /docs should return 200, got {docs_3000.status_code}"

    # Check /http-api/search without token returns 401
    time.sleep(1)
    search_3000 = requests.post(f"{PROXY_URL}/http-api/search", json={"query": "test"}, timeout=30)
    assert search_3000.status_code == 401, "Proxy /http-api/search should return 401 without auth"

    search_8000 = requests.post(f"{BACKEND_URL}/http-api/search", json={"query": "test"}, timeout=30)
    assert search_8000.status_code == 401, "Backend /http-api/search should return 401 without auth"

    # Configure the app by posting to /auth
    auth_payload = {
        "serverUrl": "http://joplin:22300",  # internal network name
        "username": "admin@localhost",
        "password": "admin",
        "masterPassword": "test_master_password",
        "rotate": True
    }

    # Actually wait for the app service to be fully up
    max_retries = 60
    for i in range(max_retries):
        try:
            r = requests.get(f"{PROXY_URL}/", auth=("setup", "1-mcp-server"), timeout=5)
            if r.status_code == 200:
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
            pass
        time.sleep(1)

    # The Joplin server inside the docker container might take a few extra seconds 
    # to run DB migrations and expose the /api/sessions endpoint. We need to retry the auth payload.
    auth_success = False
    last_err = ""
    for i in range(30):
        try:
            auth_resp = requests.post(f"{PROXY_URL}/auth", json=auth_payload, auth=("setup", "1-mcp-server"), timeout=5)
            if auth_resp.status_code == 200:
                auth_success = True
                break
            last_err = auth_resp.text
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            last_err = str(e)
        time.sleep(2)

    assert auth_success, f"Failed to authenticate setup after retries: {last_err}"

    # Wait for the config to be written and system locked
    time.sleep(2)

    key_resp = requests.post(f"{PROXY_URL}/auth/keys/create", json={"annotation": "E2E API Key"}, auth=("admin@localhost", "admin"), timeout=30)
    assert key_resp.status_code == 200, f"Failed to create key: {key_resp.text}"
    token = key_resp.json().get("key", {}).get("key")
    assert token, "Token should be returned"

    headers = {"Authorization": f"Bearer {token}"}

    # Wait for the backend and proxy to pick up the new config if needed, and for Joplin to be ready.
    time.sleep(2)

    # Wait for Ollama to pull the model
    print("Waiting for Ollama to pull nomic-embed-text...")
    for _ in range(60):
        try:
            # We can hit the backend's get_embedding by proxying through, but it's simpler to just retry remember
            pass
        except Exception:
            pass

        # Alternatively, hit ollama directly, but we didn't expose it to localhost in the test compose file? 
        # Wait, docker-compose.test.yml exposes ollama on 11434.
        try:
            ollama_resp = requests.get("http://localhost:11434/api/tags", timeout=30)
            if ollama_resp.status_code == 200:
                models = ollama_resp.json().get("models", [])
                if any("nomic-embed-text" in m.get("name", "") for m in models):
                    print("Ollama model ready!")
                    break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)

    # 2. Use /http-api/remember to create data
    secret_uuid = str(uuid.uuid4())
    remember_payload = {
        "title": "E2E Test Note",
        "content": f"The secret E2E value is {secret_uuid}"
    }

    remember_resp = requests.post(f"{PROXY_URL}/http-api/remember", json=remember_payload, headers=headers, timeout=30)
    assert remember_resp.status_code == 200, f"Remember API failed: {remember_resp.text}"

    print("REMEMBER RESPONSE:", remember_resp.text)
    note_id = remember_resp.json().get("id")
    assert note_id, "Note ID should be returned"

    # Allow time for sync, embedding generation, and vector DB insertion
    print("Waiting for note to be embedded and synced...")

    # 3. Use /http-api/search to retrieve that data (polling until ready)
    search_data = []
    for _ in range(30):
        try:
            search_resp = requests.post(f"{PROXY_URL}/http-api/search", json={"query": secret_uuid}, headers=headers, timeout=30)
            if search_resp.status_code == 200:
                search_data = search_resp.json()
                if len(search_data) > 0:
                    break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)

    assert len(search_data) > 0, "No results returned for search"
    assert search_data[0]["id"] == note_id, "The top result should be the note we just created"

    # 4. Perform the same search against the backend port directly
    search_resp_backend = requests.post(f"{BACKEND_URL}/http-api/search", json={"query": secret_uuid}, headers=headers, timeout=30)
    assert search_resp_backend.status_code == 200, f"Backend Search API failed: {search_resp_backend.text}"

    search_data_backend = search_resp_backend.json()
    assert len(search_data_backend) > 0, "No results returned for backend search"
    assert search_data_backend[0]["id"] == note_id, "The backend top result should be the note we just created"

    # --- NEW: Test Advanced Settings Flow ---
    print("[E2E] Testing advanced settings and dynamic embedding model probe...", file=sys.stderr)

    # 1. Test a fake model probe (should fail)
    fake_probe_payload = {
        "provider": "ollama",
        "baseUrl": "http://ollama:11434",
        "model": "fake-model-that-doesnt-exist"
    }
    probe_fail_resp = requests.post(f"{PROXY_URL}/api/settings/test-model", json=fake_probe_payload, headers=headers, timeout=30)
    assert probe_fail_resp.status_code in [400, 422], f"Expected probe to fail for fake model, got {probe_fail_resp.status_code}"

    # 2. Test a valid model probe (should succeed since docker-compose.test.yml runs ollama with nomic-embed-text)
    valid_probe_payload = {
        "provider": "ollama",
        "baseUrl": "http://ollama:11434",
        "model": "nomic-embed-text"
    }
    probe_success_resp = requests.post(f"{PROXY_URL}/api/settings/test-model", json=valid_probe_payload, headers=headers, timeout=30)
    assert probe_success_resp.status_code == 200, f"Expected probe to succeed, got: {probe_success_resp.text}"
    probe_data = probe_success_resp.json()
    assert probe_data.get("dimension") == 768, f"Expected dimension 768 from nomic-embed-text, got {probe_data}"

    # 3. Update settings and trigger a reindex
    update_payload = {
        "embedding": {
            "provider": "ollama",
            "baseUrl": "http://ollama:11434",
            "model": "nomic-embed-text"
        }
    }
    try:
        update_resp = requests.post(f"{PROXY_URL}/api/reindex", json=update_payload, headers=headers, timeout=30)
        # In rare cases, the response might sneak out before the container fully dies
        assert update_resp.status_code == 200, f"Failed to update settings: {update_resp.text}"
    except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
        # This is expected! The REINDEX operation uses the Maintenance Shutdown Procedure,
        # which intentionally kills the container (causing a RemoteDisconnected error)
        # before the HTTP response can fully stream back.
        print("[E2E] Connection dropped as expected during Maintenance Shutdown Protocol.", file=sys.stderr)

    print("[E2E] Settings updated successfully. Awaiting Node.js daemon restart and re-sync...", file=sys.stderr)

    # Wait for the app container to be ready again
    for _ in range(30):
        try:
            if requests.get(f"{PROXY_URL}/", timeout=2).status_code == 200:
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
            pass
        time.sleep(1)

    # Re-authenticate because the Node proxy lost the in-memory password during restart
    auth_success = False
    for _ in range(15):
        try:
            reauth_resp = requests.post(f"{PROXY_URL}/auth", json=auth_payload, auth=("admin@localhost", "admin"), timeout=5)
            if reauth_resp.status_code == 200:
                auth_success = True
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
            pass
        time.sleep(2)
    assert auth_success, "Failed to re-authenticate after Node proxy restart"
    # 4. Verify search still works with the newly dimensioned database    search_data_after = []
    for _ in range(30):
        try:
            search_resp_after = requests.post(f"{PROXY_URL}/http-api/search", json={"query": secret_uuid}, headers=headers, timeout=30)
            if search_resp_after.status_code == 200:
                search_data_after = search_resp_after.json()
                if len(search_data_after) > 0:
                    break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)        
    assert len(search_data_after) > 0, "No results returned after re-index"
    assert search_data_after[0]["id"] == note_id, "The backend top result should still be our note after re-index"

    print("[E2E] Advanced settings flow completed successfully.", file=sys.stderr)
