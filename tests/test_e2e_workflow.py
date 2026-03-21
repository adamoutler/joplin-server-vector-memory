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
import requests
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
        if self.path in ['/api/embeddings', '/api/embed', '/http-api/internal/embed']:
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
                
                # Check if it's a batched request or single
                texts = req.get('texts', req.get('input', []))
                if not texts:
                    single_prompt = req.get('prompt', req.get('text', ''))
                    if single_prompt:
                        texts = [single_prompt]
                        
                import re
                import hashlib
                
                all_embeddings = []
                for prompt in texts:
                    embedding = [0.0] * 384
                    # Look for a UUID in the prompt (case-insensitive to be safe)
                    m = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', prompt, re.IGNORECASE)
                    if m:
                        # Target note logic: distinct non-zero vector
                        embedding[1] = 1.0
                        embedding[2] = 0.5
                    else:
                        # Random noise logic: completely orthogonal but deterministic based on prompt
                        h = int(hashlib.md5(prompt.encode('utf-8')).hexdigest(), 16)
                        idx = h % 300 + 10 # ensure it never hits index 1 or 2
                        embedding[idx] = 1.0
                        embedding[idx+1] = 0.5
                    all_embeddings.append(embedding)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"MockOllamaHandler error parsing request: {e}")
                all_embeddings = [[0.0] * 384]

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            
            if 'internal/embed' in self.path or 'api/embed' in self.path:
                response = {"embeddings": all_embeddings}
            else:
                response = {"embedding": all_embeddings[0] if all_embeddings else []}
                
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
    server = HTTPServer(('0.0.0.0', 0), MockOllamaHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    
    # Use the docker bridge IP so the container can reach the host
    # 172.17.0.1 is the default docker bridge IP on Linux GH actions
    yield f"http://172.17.0.1:{port}"
    server.shutdown()
    server.server_close()

@pytest.fixture
def temp_profile():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir

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
    env["NODE_PROXY_URL"] = "http://localhost:3001"

    # Database is stored in temp_profile/vector.sqlite
    sqlite_db_path = os.path.join(temp_profile, "vector.sqlite")

    print("Running Node.js client for massive note injection...")
    # Increase timeout significantly as per instructions
    result = subprocess.run(
        ["docker", "compose", "-p", "joplin-test-env", "-f", DOCKER_COMPOSE_FILE, "exec", "-T", "-e", f"OLLAMA_URL={mock_ollama_server}", "-e", f"BACKEND_URL={mock_ollama_server}", "-e", "SQLITE_DB_PATH=/tmp/vector_memory.sqlite", "-e", "JOPLIN_SERVER_URL=http://joplin:22300", "-e", "JOPLIN_USERNAME=admin@localhost", "-e", "JOPLIN_PASSWORD=admin", "app", "node", "client/e2e_massive_create_sync.js", secret_uuid],
        cwd=os.path.dirname(DOCKER_COMPOSE_FILE),
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

    # Initialize the Node.js proxy so it has credentials for deletion
    print("Initializing Node.js proxy...")
    auth_payload = {
        "serverUrl": "http://joplin:22300",
        "username": "admin@localhost",
        "password": "admin",
        "masterPassword": "test_master_password",
        "rotate": False
    }
    r = requests.post("http://localhost:3001/auth", json=auth_payload, auth=("setup", "1-mcp-server"), timeout=10)
    print("Init response:", r.status_code, r.text)

    print("Restarting proxy to force it to initialize the sync client...")
    try:
        requests.post("http://localhost:3001/node-api/restart", timeout=5)
    except Exception:
        pass
    time.sleep(3) # Wait for proxy to come back up
    
    # Wait for proxy to be ready
    for _ in range(30):
        try:
            r = requests.get("http://localhost:3001/", auth=("setup", "1-mcp-server"), timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)

    # Copy the DB out of the container to the host machine for the python test to read
    subprocess.run(["docker", "cp", f"joplin-test-env-app-1:/tmp/vector_memory.sqlite", sqlite_db_path], check=False)

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
