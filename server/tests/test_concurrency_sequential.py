import sys
import os
import subprocess


def test_concurrent_mutations_are_sequential():
    # We test the sequential locking by running a separate python process
    # so we don't mess up the pytest environment's global state.

    script = """
import sys
import os
import threading
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import src.main

active_requests = 0
max_active = 0
tracker_lock = threading.Lock()

def mock_post(*args, **kwargs):
    global active_requests, max_active
    with tracker_lock:
        active_requests += 1
        if active_requests > max_active:
            max_active = active_requests

    time.sleep(0.05)

    with tracker_lock:
        active_requests -= 1

    resp = MagicMock()
    resp.status_code = 200
    return resp

with patch('requests.post', side_effect=mock_post):
    src.main.get_config = lambda: {"joplin_username": "a", "joplin_password": "b"}
    real_call_node_proxy = src.main._call_node_proxy

    threads = []
    for i in range(5):
        t = threading.Thread(target=real_call_node_proxy, args=("POST", "/node-api/notes", {"test": i}))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    if max_active != 1:
        print(f"FAILED: max_active was {max_active}")
        sys.exit(1)
    else:
        print("SUCCESS")
        sys.exit(0)
"""

    # Run the script
    script_path = os.path.join(os.path.dirname(__file__), "run_concurrency_test.py")
    with open(script_path, "w") as f:
        f.write(script)

    try:
        res = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        assert res.returncode == 0, f"Concurrency test failed: {res.stdout}\n{res.stderr}"
        assert "SUCCESS" in res.stdout
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)
