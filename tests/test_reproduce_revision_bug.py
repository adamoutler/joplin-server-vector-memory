import os
import sys
import time
import requests

# Make sure we can import the ephemeral_joplin fixture
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server', 'tests')))


def wait_for_server(port, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"http://localhost:{port}/status")
            if r.status_code in [200, 401]:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    return False


def test_revision_service_bug(ephemeral_joplin):
    """
    Reproduces the bug where BaseItem.revisionService_ is not set
    1. Start sync app
    2. Stop sync app
    3. Modify note via Joplin API
    4. Start sync app
    5. Force sync -> triggers bug
    """
    # The app is already running on port 3001 via docker-compose
    app_url = "http://localhost:3001"
    joplin_internal_url = "http://joplin:22300"
    joplin_external_url = "http://localhost:22300"
    email = "admin@localhost"
    password = "admin"

    import base64
    auth_header = "Basic " + base64.b64encode(f"{email}:{password}".encode('utf-8')).decode('utf-8')
    headers = {"Authorization": auth_header}

    assert wait_for_server(3001), "Node server failed to start"

    print("Configuring sync app...")
    # Configure and start sync
    r = requests.post(f"{app_url}/auth", json={
        "serverUrl": joplin_internal_url,
        "username": email,
        "password": password,
        "memoryServerAddress": "http://ollama:11434",
        "masterPassword": ""
    }, headers=headers)
    assert r.status_code == 200, f"Auth failed: {r.text}"

    # Wait for sync to complete
    sync_complete = False
    for _ in range(30):
        r = requests.get(f"{app_url}/status", headers=headers)
        if r.status_code == 200:
            st = r.json()
            if st.get('syncState', {}).get('status') == 'ready':
                sync_complete = True
                break
            if st.get('syncState', {}).get('status') == 'error':
                print("Sync error:", st.get('syncState', {}).get('error'))
        time.sleep(1)

    assert sync_complete, "Initial sync failed to complete"

    # 2. Stop sync app (Restarting it via the API)
    print("Restarting app...")
    requests.post(f"{app_url}/node-api/restart", headers=headers)
    time.sleep(3)  # Wait for it to die
    assert wait_for_server(3001), "Node server failed to come back up"

    # 3. Create a note on the remote Joplin Server to force a sync download on next run
    print("Creating remote note...")
    # First get a session token directly to joplin (using Host header to bypass 404 issue if needed)
    r = requests.post(f"{joplin_external_url}/api/sessions", headers={"Host": "joplin:22300"}, json={"email": email, "password": password})
    assert r.status_code == 200
    session_id = r.json()["id"]

    note_content = "Remote Note\n\nSome body\n\nid: 00000000000000000000000000000001\nparent_id: 00000000000000000000000000000002\ntype_: 1"
    r = requests.put(f"{joplin_external_url}/api/items/root:/00000000000000000000000000000001.md:/content", headers={"Host": "joplin:22300", "X-API-AUTH": session_id, "Content-Type": "application/octet-stream"}, data=note_content.encode('utf-8'))
    assert r.status_code == 200, f"Failed to create remote note: {r.text}"

    # 4. Wait for Node app to be fully ready
    # Check status
    time.sleep(2)

    # 5. Force sync
    print("Forcing sync...")
    r = requests.post(f"{app_url}/sync", headers=headers)

    # Monitor status for the error
    error_found = False
    for _ in range(15):
        r = requests.get(f"{app_url}/status", headers=headers)
        if r.status_code == 200:
            st = r.json()
            if st.get('syncState', {}).get('status') == 'error':
                err_msg = st.get('syncState', {}).get('error', '')
                print("Observed sync error:", err_msg)
                if 'revisionService_ is not set' in err_msg:
                    error_found = True
                    break
        time.sleep(1)

    assert not error_found, "Observed the 'revisionService_ is not set' bug! It should be fixed."
    print("BUG FIX SUCCESSFULLY VERIFIED - sync completed without errors after restart")
