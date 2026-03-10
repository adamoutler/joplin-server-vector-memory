import pytest
import asyncio
import os
import sys
import tempfile
import json
import threading
import subprocess
import time
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

# Mock Ollama Server
class MockOllamaHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/embeddings':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            req = json.loads(post_data)
            
            # Simple mock: if prompt has "E2E Secret", give a specific embedding, else a default one
            embedding = [0.0] * 768
            if "E2E Secret" in req.get('prompt', ''):
                embedding[0] = 1.0
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"embedding": embedding}
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logs

@pytest.fixture(scope="module")
def mock_ollama_server():
    server = HTTPServer(('127.0.0.1', 0), MockOllamaHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    yield path
    os.close(fd)
    try:
        os.remove(path)
    except OSError:
        pass

def test_e2e_mcp_flow(mock_ollama_server, temp_db):
    asyncio.run(run_e2e_mcp_flow(mock_ollama_server, temp_db))

async def run_e2e_mcp_flow(mock_ollama_server, temp_db):
    port = get_free_port()
    env = os.environ.copy()
    env["OLLAMA_URL"] = mock_ollama_server
    env["SQLITE_DB_PATH"] = temp_db
    env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    import urllib.request
    import urllib.error
    
    ready = False
    for i in range(20):
        try:
            # We can check the /docs or /http-api/mcp/sse/sse or just root, but fastmcp might not have root.
            # Just opening a TCP connection to the port is enough
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                ready = True
                break
        except Exception:
            time.sleep(0.5)
            
    if not ready:
        server_process.terminate()
        stdout, stderr = server_process.communicate()
        pytest.fail(f"Server failed to start. Stdout: {stdout.decode()} \n Stderr: {stderr.decode()}")

    
    url = f"http://127.0.0.1:{port}/http-api/mcp/sse/"
    
    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # 1. Call remember
                fake_uuid = "123e4567-e89b-12d3-a456-426614174000"
                remember_res = await session.call_tool(
                    "remember",
                    arguments={"title": "E2E Secret Memory", "content": fake_uuid}
                )
                
                try:
                    remember_data = json.loads(remember_res.content[0].text)
                    note_id = remember_data.get("id")
                except Exception:
                    pytest.fail(f"Could not parse remember response as JSON: {remember_res.content[0].text}")
                    
                assert remember_data.get("status") == "success", "Failed to remember"
                
                # 2. Call search_notes
                search_res = await session.call_tool(
                    "search_notes",
                    arguments={"query": "E2E Secret"}
                )
                search_data = json.loads(search_res.content[0].text)
                assert isinstance(search_data, list)
                assert any(note.get("id") == note_id and note.get("blurb") == fake_uuid for note in search_data)
                
                # 3. Call get_note
                get_res = await session.call_tool(
                    "get_note",
                    arguments={"note_id": note_id}
                )
                get_data = json.loads(get_res.content[0].text)
                assert get_data.get("id") == note_id
                assert get_data.get("title") == "[Agent Memory] E2E Secret Memory"
                assert get_data.get("content") == fake_uuid
                content_hash = get_data.get("content_hash")
                
                # 4a. Attempt to execute_deletion with made-up token
                bad_exec_res = await session.call_tool(
                    "execute_deletion",
                    arguments={
                        "deletion_token": "made_up_token",
                        "confirm_title": "[Agent Memory] E2E Secret Memory",
                        "safety_attestation": {
                            "content_hash": content_hash,
                            "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
                        }
                    }
                )
                bad_exec_data = json.loads(bad_exec_res.content[0].text)
                assert "error" in bad_exec_data
                
                # 4b. Request deletion
                req_res = await session.call_tool(
                    "request_note_deletion",
                    arguments={"note_id": note_id, "reason": "Test deletion"}
                )
                req_data = json.loads(req_res.content[0].text)
                assert req_data.get("status") == "pending"
                token = req_data.get("deletion_token")
                
                # 4c. Attempt execute_deletion with incorrect confirm_title
                bad_title_res = await session.call_tool(
                    "execute_deletion",
                    arguments={
                        "deletion_token": token,
                        "confirm_title": "Wrong Title",
                        "safety_attestation": {
                            "content_hash": content_hash,
                            "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
                        }
                    }
                )
                bad_title_data = json.loads(bad_title_res.content[0].text)
                assert "error" in bad_title_data
                
                # 4d. Attempt execute_deletion with incorrect safety_attestation (wrong hash)
                bad_att_res = await session.call_tool(
                    "execute_deletion",
                    arguments={
                        "deletion_token": token,
                        "confirm_title": "[Agent Memory] E2E Secret Memory",
                        "safety_attestation": {
                            "content_hash": "sha256:wronghash",
                            "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
                        }
                    }
                )
                bad_att_data = json.loads(bad_att_res.content[0].text)
                assert "error" in bad_att_data
                
                # 4e. Call execute_deletion successfully
                del_res = await session.call_tool(
                    "execute_deletion",
                    arguments={
                        "deletion_token": token,
                        "confirm_title": "[Agent Memory] E2E Secret Memory",
                        "safety_attestation": {
                            "content_hash": content_hash,
                            "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
                        }
                    }
                )
                del_data = json.loads(del_res.content[0].text)
                assert del_data.get("status") == "success"
                
                # 5. Call search_notes again
                search_res_2 = await session.call_tool(
                    "search_notes",
                    arguments={"query": "E2E Secret"}
                )
                
                if not search_res_2.content:
                    search_data_2 = []
                else:
                    search_data_2 = json.loads(search_res_2.content[0].text)
                    
                assert not any(note.get("id") == note_id for note in search_data_2)
    finally:
        # Clean up
        server_process.terminate()
        server_process.wait()
        stdout, stderr = server_process.communicate()
        print("Uvicorn stderr:", stderr.decode())

import requests

def test_stateless_http_endpoint(mock_ollama_server, temp_db):
    port = get_free_port()
    env = os.environ.copy()
    env["OLLAMA_URL"] = mock_ollama_server
    env["SQLITE_DB_PATH"] = temp_db
    env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    try:
        ready = False
        for i in range(20):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)
        
        assert ready, "Server failed to start"

        # Valid initialization request
        init_payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}},
            "id": 1
        }
        
        res = requests.post(f"http://127.0.0.1:{port}/http-api/mcp/stateless/", json=init_payload, timeout=2)
        assert res.status_code == 200
        data = res.json()
        assert data.get("jsonrpc") == "2.0"
        assert data.get("id") == 1
        assert "serverInfo" in data.get("result", {})

        # Negative test (bad JSON)
        res_bad = requests.post(f"http://127.0.0.1:{port}/http-api/mcp/stateless/", data="invalid_json", headers={"Content-Type": "application/json"}, timeout=2)
        assert res_bad.status_code == 400 or (res_bad.status_code == 200 and "error" in res_bad.json())

    finally:
        server_process.terminate()
        server_process.wait()

def test_streaming_http_endpoint(mock_ollama_server, temp_db):
    port = get_free_port()
    env = os.environ.copy()
    env["OLLAMA_URL"] = mock_ollama_server
    env["SQLITE_DB_PATH"] = temp_db
    env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    try:
        ready = False
        for i in range(20):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)
        
        assert ready, "Server failed to start"

        init_payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}},
            "id": 2
        }
        
        # We need to send application/json but accept both
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        
        res = requests.post(f"http://127.0.0.1:{port}/http-api/mcp/stream/", json=init_payload, headers=headers, timeout=5)
        assert res.status_code == 200
        # Check if it streamed (transfer-encoding chunked or fastmcp JSON response)
        content = res.content.decode()
        assert "jsonrpc" in content
        assert "id" in content

    finally:
        server_process.terminate()
        server_process.wait()
