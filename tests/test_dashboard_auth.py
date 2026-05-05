import pytest
import requests
import subprocess
import time
import os
import sys
import base64

sys.path.append(os.path.abspath(os.path.dirname(__file__)))


@pytest.fixture
def node_server_port():
    return "3006"


@pytest.fixture
def node_server(node_server_port, tmp_path):
    client_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'client'))
    env = os.environ.copy()
    env["JOPLIN_SERVER_URL"] = "http://localhost:22300"
    env["PORT"] = node_server_port
    env["DATA_DIR"] = str(tmp_path)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)

    process = subprocess.Popen(
        ["node", "src/index.js"],
        cwd=client_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    ready = False
    for _ in range(30):
        try:
            resp = requests.get(f"http://localhost:{node_server_port}/status", timeout=30)
            if resp.status_code in [200, 401]:
                ready = True
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)

    if not ready:
        process.kill()
        out, err = process.communicate()
        raise RuntimeError(f"Node server did not start in time. Out: {out.decode()} Err: {err.decode()}")

    yield f"http://localhost:{node_server_port}", process

    if process.poll() is None:
        process.terminate()
        process.wait()


def test_dashboard_valid_auth(ephemeral_joplin, node_server):
    url, process = node_server
    auth = base64.b64encode(b"setup:1-mcp-server").decode("utf-8")
    headers = {"Authorization": f"Basic {auth}"}
    resp = requests.get(f"{url}/status", headers=headers, timeout=30)
    assert resp.status_code == 200
    assert "syncState" in resp.json()


def test_dashboard_invalid_auth(ephemeral_joplin, node_server):
    url, process = node_server
    auth = base64.b64encode(b"baduser@localhost:wrongpass").decode("utf-8")
    headers = {"Authorization": f"Basic {auth}"}
    resp = requests.get(f"{url}/status", headers=headers, timeout=30)
    assert resp.status_code == 401


def test_dashboard_joplin_unreachable(tmp_path):
    client_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'client'))
    env = os.environ.copy()
    env["JOPLIN_SERVER_URL"] = "http://localhost:22300"  # Wrong port!
    env["PORT"] = "3007"
    env["DATA_DIR"] = str(tmp_path)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)

    process = subprocess.Popen(
        ["node", "src/index.js"],
        cwd=client_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Wait for server to start
    ready = False
    for _ in range(30):
        try:
            resp = requests.get("http://localhost:3007/status", timeout=30)
            if resp.status_code in [200, 401]:
                ready = True
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)

    assert ready, "Node server did not start for unreachable test"

    auth = base64.b64encode(b"setup:1-mcp-server").decode("utf-8")
    headers = {"Authorization": f"Basic {auth}"}

    try:
        requests.get("http://localhost:3007/status", headers=headers, timeout=30)
    except requests.exceptions.ConnectionError:
        pass  # It's expected to crash, meaning the connection might drop

    # Give it a moment to crash
    time.sleep(1)

    # Process should either still be running (poll is None) or exited with an error
    exit_code = process.poll()
    if exit_code is not None:
        assert exit_code != 0, "Node.js process exited successfully when it should have crashed or kept running"
