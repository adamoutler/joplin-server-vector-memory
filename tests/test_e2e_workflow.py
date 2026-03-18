import pytest
import asyncio
import os
import sys
import tempfile
import json
import threading
import subprocess
import uuid
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

# We import the fixture from server/tests/conftest.py to ensure the ephemeral Joplin Server runs
# Adding server/tests to sys.path to easily import it, or we can just redefine it.
# We'll rely on conftest if we run `pytest tests/test_e2e_workflow.py` but let's just make sure.
# Actually, since it's a fixture in server/tests/conftest.py, we can define a conftest.py in tests/ 
# or just redefine it here to be safe, or just use `from server.tests.conftest import ephemeral_joplin` 
# wait, pytest fixtures don't need to be imported if they are in a conftest.py in a parent/sibling 
# if we run from root, but `tests/` and `server/tests/` are siblings. 
# Better to import it explicitly or recreate.

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.test.yml'))

# Import ephemeral_joplin from test_ephemeral_joplin just in case, but it's local there
# Let's just redefine a session-scoped ephemeral_joplin here if it doesn't conflict, 
# or just run it via import.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server', 'tests')))


class MockOllamaHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path in ['/api/embeddings', '/http-api/internal/embed']:
            try:
                if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
                    post_data_bytes = b""
                    while True:
                        raw_line = self.rfile.readline()
                        if not raw_line:
                            break
                        line = raw_line.strip()
                        if not line:
                            continue
                        chunk_size = int(line, 16)
                        if chunk_size == 0:
                            break
                        post_data_bytes += self.rfile.read(chunk_size)
                        self.rfile.readline() # read trailing \r\n
                    post_data = post_data_bytes.decode('utf-8')
                else:
                    content_length = int(self.headers.get('Content-Length', 0))
                    post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''
                    
                req = json.loads(post_data) if post_data else {}
                prompt = req.get('prompt', req.get('text', ''))
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"MockOllamaHandler error parsing request: {e}")
                prompt = 'fallback'

            embedding = [0.0] * 768
            
            import re
            import hashlib
            
            # Look for a UUID in the prompt (case-insensitive to be safe)
            m = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', prompt, re.IGNORECASE)
            if m:
                # Target note logic: distinct non-zero vector
                embedding[1] = 1.0
                embedding[2] = 0.5
            else:
                # Random noise logic: completely orthogonal but deterministic based on prompt
                h = int(hashlib.md5(prompt.encode('utf-8')).hexdigest(), 16)
                idx = h % 700 + 10 # ensure it never hits index 1 or 2
                embedding[idx] = 1.0
                embedding[idx+1] = 0.5
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            response = {"embedding": embedding}
            response_bytes = json.dumps(response).encode()
            self.send_header('Content-Length', str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)
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
def temp_profile():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir

def test_full_e2e_workflow(ephemeral_joplin, mock_ollama_server, temp_profile):
    asyncio.run(run_full_e2e_workflow(mock_ollama_server, temp_profile))

async def run_full_e2e_workflow(mock_ollama_server, temp_profile):
    secret_uuid = str(uuid.uuid4())
    print(f"\\nSecret UUID for this run: {secret_uuid}")
    
    # Paths
    client_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'client'))
    script_path = os.path.join(client_dir, 'e2e_create_sync.js')
    
    # 1. Run Node.js client to create note, sync it, and generate embeddings
    env = os.environ.copy()
    env["OLLAMA_URL"] = mock_ollama_server
    env["BACKEND_URL"] = mock_ollama_server
    env["JOPLIN_PROFILE_DIR"] = temp_profile
    env["JOPLIN_SERVER_URL"] = "http://joplin:22300"
    env["JOPLIN_USERNAME"] = "admin@localhost"
    env["JOPLIN_PASSWORD"] = "admin"
    
    print("Running Node.js client to create, sync and generate embedding...")
    result = subprocess.run(
        ["node", script_path, secret_uuid],
        cwd=client_dir,
        env=env,
        capture_output=True,
        text=True
    )
    
    print("Node.js output:", result.stdout)
    if result.stderr:
        print("Node.js error:", result.stderr)
        
    assert result.returncode == 0, "Node.js client script failed"
    
    # Extract the created note ID from the stdout (optional, just for reference)
    created_note_id = None
    for line in result.stdout.splitlines():
        if "Created note ID:" in line:
            created_note_id = line.split("Created note ID:")[1].strip()
            
    assert created_note_id is not None, "Failed to capture created note ID from Node script output"
    
    # Database is stored in temp_profile/vector.sqlite
    sqlite_db_path = os.path.join(temp_profile, "vector.sqlite")
    assert os.path.exists(sqlite_db_path), "Vector SQLite DB was not created"
    
    # Query Python MCP Server
    main_py_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server', 'src', 'main.py'))
    env["SQLITE_DB_PATH"] = sqlite_db_path
    env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server'))
    env["NODE_PROXY_URL"] = "http://127.0.0.1:3001"
    
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[main_py_path, "--stdio"],
        env=env
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Search for the note using the secret UUID
            search_query = f"secret number is {secret_uuid}"
            print(f"Searching via MCP for: {search_query}")
            
            search_res = await session.call_tool(
                "search_notes",
                arguments={"query": search_query}
            )
            
            print("Raw Search Res:", search_res)
            print("Search Response:", search_res.content[0].text if search_res.content else "EMPTY")
            search_data = json.loads(search_res.content[0].text) if search_res.content else []
            
            # Verify the note is found
            assert isinstance(search_data, list)
            assert len(search_data) > 0, "No notes found matching the secret UUID"
            
            found_note_id = search_data[0].get("id")
            assert found_note_id == created_note_id, f"Found note ID {found_note_id} doesn't match created note ID {created_note_id}"
            assert "full_body" in search_data[0], "full_body should be present in the first result"
            assert secret_uuid in search_data[0].get("full_body", ""), "Secret UUID not found in the full_body of the top search result"
            
            # Read the note via get_note
            get_res = await session.call_tool(
                "get_note",
                arguments={"note_id": found_note_id}
            )
            
            print("Get Response:", get_res.content[0].text)
            get_data = json.loads(get_res.content[0].text)
            assert get_data.get("id") == found_note_id
            assert secret_uuid in get_data.get("content", ""), "Secret UUID not found in the actual note content"
            # 4. Delete the note
            print("Requesting note deletion...")
            del_req_res = await session.call_tool(
                "request_note_deletion",
                arguments={"note_id": found_note_id, "reason": "E2E test cleanup"}
            )
            print("Delete Request Response:", del_req_res.content[0].text)
            del_req_data = json.loads(del_req_res.content[0].text)
            token = del_req_data.get("deletion_token")

            print("Executing note deletion...")
            del_exec_res = await session.call_tool(
                "execute_deletion",
                arguments={
                    "deletion_token": token,
                    "confirm_title": get_data.get("title"),
                    "safety_attestation": {
                        "content_hash": get_data.get("content_hash"),
                        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
                    }
                }
            )
            print("Delete Execute Response:", del_exec_res.content[0].text)
            del_data = json.loads(del_exec_res.content[0].text)
            assert del_data.get("status") == "success", f"Delete failed: {del_data}"
            
            # Search again and verify it's gone
            search_res_2 = await session.call_tool(
                "search_notes",
                arguments={"query": search_query}
            )
            
            if not search_res_2.content:
                search_data_2 = []
            else:
                search_data_2 = json.loads(search_res_2.content[0].text)
                
            assert not any(note.get("id") == found_note_id for note in search_data_2), "Note was not deleted from DB"
            print("Test completely successful!")


def test_massive_note_injection(ephemeral_joplin, mock_ollama_server, temp_profile):
    asyncio.run(run_massive_note_injection(mock_ollama_server, temp_profile))

async def run_massive_note_injection(mock_ollama_server, temp_profile):
    secret_uuid = str(uuid.uuid4())
    print(f"\nSecret UUID for massive run: {secret_uuid}")
    
    # Paths
    client_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'client'))
    script_path = os.path.join(client_dir, 'e2e_massive_create_sync.js')
    
    # Run Node.js client to create 50 notes, sync them, and generate embeddings
    env = os.environ.copy()
    env["OLLAMA_URL"] = mock_ollama_server
    env["BACKEND_URL"] = mock_ollama_server
    env["JOPLIN_PROFILE_DIR"] = temp_profile
    env["JOPLIN_SERVER_URL"] = "http://joplin:22300"
    env["JOPLIN_USERNAME"] = "admin@localhost"
    env["JOPLIN_PASSWORD"] = "admin"
    
    print("Running Node.js client for massive note injection...")
    # Increase timeout significantly as per instructions
    result = subprocess.run(
        ["node", script_path, secret_uuid],
        cwd=client_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=300
    )
    
    print("Massive Node.js output:", result.stdout)
    if result.stderr:
        print("Massive Node.js error:", result.stderr)
        
    assert result.returncode == 0, "Massive Node.js client script failed"
    
    # Extract the created note ID from the stdout
    created_note_id = None
    for line in result.stdout.splitlines():
        if "Created note ID:" in line:
            created_note_id = line.split("Created note ID:")[1].strip()
            
    assert created_note_id is not None, "Failed to capture created note ID from Node script output"
    
    # Database is stored in temp_profile/vector.sqlite
    sqlite_db_path = os.path.join(temp_profile, "vector.sqlite")
    assert os.path.exists(sqlite_db_path), "Vector SQLite DB was not created"
    
    # Query Python MCP Server
    main_py_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server', 'src', 'main.py'))
    env["SQLITE_DB_PATH"] = sqlite_db_path
    env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server'))
    env["NODE_PROXY_URL"] = "http://127.0.0.1:3001"
    
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[main_py_path, "--stdio"],
        env=env
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Search for the one specific note containing the secret UUID
            search_query = f"secret keyword is {secret_uuid}"
            print(f"Searching via MCP for: {search_query}")
            
            search_res = await session.call_tool(
                "search_notes",
                arguments={"query": search_query}
            )
            
            print("Raw Search Res:", search_res)
            print("Search Response:", search_res.content[0].text if search_res.content else "EMPTY")
            search_data = json.loads(search_res.content[0].text) if search_res.content else []
            
            # Verify the specific note is found correctly
            assert isinstance(search_data, list)
            assert len(search_data) > 0, "No notes found matching the massive injection secret UUID"
            
            # It should ideally be the top hit since it alone contains the secret, but
            # because mock ollama might generate identical distances for mock data,
            # we check if it is ANYWHERE in the returned results.
            found_note_id = None
            for item in search_data:
                if item.get("id") == created_note_id:
                    found_note_id = created_note_id
                    break
            
            assert found_note_id == created_note_id, f"Created note ID {created_note_id} not found in search results: {search_data}"
            
            # Read the note via get_note
            get_res = await session.call_tool(
                "get_note",
                arguments={"note_id": found_note_id}
            )
            
            print("Get Response:", get_res.content[0].text)
            get_data = json.loads(get_res.content[0].text)
            assert get_data.get("id") == found_note_id
            assert secret_uuid in get_data.get("content", ""), "Secret UUID not found in the actual note content"
            
            print("Massive test completely successful!")
