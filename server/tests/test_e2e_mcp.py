import pytest
import requests
import json
import sys
import os
from urllib.parse import urljoin

# Import the ephemeral_joplin fixture
sys.path.append(os.path.abspath(os.path.dirname(__file__)))


@pytest.mark.enable_socket
def test_sse_endpoint(ephemeral_joplin):
    base_url = "http://localhost:8002"
    sse_url = f"{base_url}/http-api/mcp/sse"

    # Start the SSE connection
    resp = requests.get(sse_url, headers={"Accept": "text/event-stream"}, stream=True, timeout=30)
    assert resp.status_code == 200, f"Failed to connect to SSE: {resp.status_code}"

    endpoint_url = None
    is_endpoint_event = False

    for line in resp.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("event: endpoint"):
                is_endpoint_event = True
            elif is_endpoint_event and decoded_line.startswith("data: "):
                endpoint_url = decoded_line[len("data: "):].strip()
                break

    assert endpoint_url is not None, "Did not receive endpoint URL from SSE handshake"

    # Handle relative or absolute URLs
    if endpoint_url.startswith("/"):
        post_url = urljoin(base_url, endpoint_url)
    else:
        post_url = endpoint_url

    print(f"Discovered POST endpoint: {post_url}")

    # Now POST to the endpoint
    init_msg = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"}
        },
        "id": 1
    }

    post_resp = requests.post(post_url, json=init_msg, timeout=30)
    assert post_resp.status_code in [200, 202], f"Failed to POST to endpoint: {post_resp.status_code}"

    # Since it's SSE, the response to the initialization might come back on the SSE stream
    # but we proved the handshake and POST routing works.


@pytest.mark.enable_socket
def test_stream_endpoint(ephemeral_joplin):
    url = "http://localhost:8002/http-api/mcp/stream"
    init_msg = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"}
        },
        "id": 1
    }

    # The middleware now sets the correct Accept header for us, but it's good practice to send it
    headers = {"Accept": "application/json, text/event-stream"}
    resp = requests.post(url, json=init_msg, headers=headers, stream=True, timeout=30)
    assert resp.status_code == 200, f"Stream endpoint returned {resp.status_code}"

    received_result = False
    is_message_event = False

    for line in resp.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("event: message"):
                is_message_event = True
            elif is_message_event and decoded_line.startswith("data: "):
                data_str = decoded_line[len("data: "):].strip()
                try:
                    data_json = json.loads(data_str)
                    if "result" in data_json and "protocolVersion" in data_json["result"]:
                        received_result = True
                        break
                except json.JSONDecodeError:
                    pass
                is_message_event = False  # reset for next event

    assert received_result, "Did not receive proper JSON-RPC initialization result from stream"


@pytest.mark.enable_socket
def test_stateless_endpoint(ephemeral_joplin):
    url = "http://localhost:8002/http-api/mcp/stateless"
    init_msg = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"}
        },
        "id": 1
    }
    resp = requests.post(url, json=init_msg, timeout=30)
    assert resp.status_code == 200, f"Stateless endpoint returned {resp.status_code}"

    data = resp.json()
    assert "result" in data
    assert "protocolVersion" in data["result"]
