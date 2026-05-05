import pytest
import requests
import os

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'docker-compose.test.yml'))


@pytest.mark.enable_socket
def test_sync_fails_with_bad_credentials(ephemeral_joplin):
    PROXY_URL = "http://localhost:3001"

    # Configure the app with a bad password
    auth_payload = {
        "serverUrl": "http://joplin:22300", 
        "username": "admin@localhost",
        "password": "wrong_" + "password",
        "masterPassword": "test_master_password",
        "rotate": True
    }

    # The /auth endpoint should now immediately test the credentials and reject them
    auth_resp = requests.post(f"{PROXY_URL}/auth", json=auth_payload, auth=("setup", "1-mcp-server"), timeout=30)
    assert auth_resp.status_code in [400, 403], f"Expected /auth to reject bad credentials, got {auth_resp.status_code}: {auth_resp.text}"

    auth_data = auth_resp.json()
    assert "Invalid username or password" in auth_data.get("error", "") or "Authentication failed" in auth_data.get("error", ""), "Expected specific error message"
