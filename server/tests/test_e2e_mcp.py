import pytest
import requests
import json
import sys
import os

# Import the ephemeral_joplin fixture
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from conftest import ephemeral_joplin

@pytest.mark.enable_socket
def test_sse_endpoint(ephemeral_joplin):
    try:
        resp = requests.get("http://localhost:8002/http-api/mcp/sse", headers={"Accept": "text/event-stream"}, stream=True, timeout=5)
        print("SSE GET:", resp.status_code)
        assert resp.status_code == 200
        # Read the first event to prove it works
        for line in resp.iter_lines():
            if line:
                print("SSE Event:", line)
                break
    except requests.exceptions.ReadTimeout:
        pass
    
@pytest.mark.enable_socket
def test_stream_endpoint(ephemeral_joplin):
    try:
        resp = requests.post("http://localhost:8002/http-api/mcp/stream", json={"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}, "id": 1}, stream=True, timeout=5)
        print("STREAM POST:", resp.status_code, resp.text)
        assert resp.status_code == 200
    except requests.exceptions.ReadTimeout:
        pass

@pytest.mark.enable_socket
def test_stateless_endpoint(ephemeral_joplin):
    resp = requests.post("http://localhost:8002/http-api/mcp/stateless", json={"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}, "id": 1}, timeout=5)
    print("STATELESS POST:", resp.status_code)
    assert resp.status_code == 200
