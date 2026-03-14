import pytest
import requests
import time
import os
import uuid
import sys

# Import the ephemeral_joplin fixture
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server', 'tests')))
from conftest import ephemeral_joplin

@pytest.mark.enable_socket
def test_api_server_live_endpoints(ephemeral_joplin):
    # ephemeral_joplin starts docker-compose.test.yml which exposes:
    # app proxy on 3001
    # app backend on 8002
    PROXY_URL = "http://localhost:3001"
    BACKEND_URL = "http://localhost:8002"

    # Verify that the ports are responding properly
    docs_8000 = requests.get(f"{BACKEND_URL}/docs")
    assert docs_8000.status_code == 200, f"Backend /docs should return 200, got {docs_8000.status_code}"

    docs_3000 = requests.get(f"{PROXY_URL}/docs")
    assert docs_3000.status_code == 200, f"Proxy /docs should return 200, got {docs_3000.status_code}"
    
    # Check /http-api/search without token returns 401
    search_3000 = requests.post(f"{PROXY_URL}/http-api/search", json={"query": "test"})
    assert search_3000.status_code == 401, "Proxy /http-api/search should return 401 without auth"
    
    search_8000 = requests.post(f"{BACKEND_URL}/http-api/search", json={"query": "test"})
    assert search_8000.status_code == 401, "Backend /http-api/search should return 401 without auth"

    # Configure the app by posting to /auth
    auth_payload = {
        "serverUrl": "http://joplin:22300", # internal network name
        "username": "admin@localhost",
        "password": "admin",
        "masterPassword": "test_master_password",
        "rotate": True
    }
    
    # Actually wait for the app service to be fully up
    max_retries = 30
    for i in range(max_retries):
        try:
            r = requests.get(f"{PROXY_URL}/")
            if r.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)

    auth_resp = requests.post(f"{PROXY_URL}/auth", json=auth_payload, auth=("admin@localhost", "admin"))
    assert auth_resp.status_code == 200, f"Failed to authenticate: {auth_resp.text}"
    token = auth_resp.json().get("token")
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
            ollama_resp = requests.get("http://localhost:11434/api/tags")
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
    
    remember_resp = requests.post(f"{PROXY_URL}/http-api/remember", json=remember_payload, headers=headers)
    assert remember_resp.status_code == 200, f"Remember API failed: {remember_resp.text}"
    
    print("REMEMBER RESPONSE:", remember_resp.text)
    note_id = remember_resp.json().get("id")
    assert note_id, "Note ID should be returned"

    # Allow time for sync, embedding generation, and vector DB insertion
    print("Waiting for note to be embedded and synced...")
    time.sleep(15)

    # 3. Use /http-api/search to retrieve that data
    search_resp = requests.post(f"{PROXY_URL}/http-api/search", json={"query": secret_uuid}, headers=headers)
    assert search_resp.status_code == 200, f"Search API failed: {search_resp.text}"
    
    search_data = search_resp.json()
    assert len(search_data) > 0, "No results returned for search"
    assert search_data[0]["id"] == note_id, "The top result should be the note we just created"

    # 4. Perform the same search against the backend port directly
    search_resp_backend = requests.post(f"{BACKEND_URL}/http-api/search", json={"query": secret_uuid}, headers=headers)
    assert search_resp_backend.status_code == 200, f"Backend Search API failed: {search_resp_backend.text}"
    
    search_data_backend = search_resp_backend.json()
    assert len(search_data_backend) > 0, "No results returned for backend search"
    assert search_data_backend[0]["id"] == note_id, "The backend top result should be the note we just created"
