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
    env["FASTMCP_MESSAGE_PATH"] = "/mcp/http/api-key/mcp/messages"
    env["FASTMCP_SSE_PATH"] = "/mcp/http/api-key/mcp/sse"
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
            # We can check the /docs or /mcp/http/api-key/mcp/sse or just root, but fastmcp might not have root.
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

    
    url = f"http://127.0.0.1:{port}/mcp/http/api-key/mcp/sse"
    
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
                assert get_data.get("title") == "E2E Secret Memory"
                assert get_data.get("content") == fake_uuid
                
                # 4. Call delete_note
                del_res = await session.call_tool(
                    "delete_note",
                    arguments={"note_id": note_id}
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
        server_process.terminate()
        server_process.wait()

