import requests
import subprocess
import time

def reset_state():
    print("Truncating Postgres DB...")
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "exec", "-T", "db", "psql", "-U", "joplin", "-d", "joplin", "-c", "TRUNCATE TABLE items, user_items, item_resources, changes, notifications, shares, share_users CASCADE;"], check=True)
    
    print("Calling /auth/wipe on Proxy...")
    try:
        requests.post("http://localhost:3000/auth/wipe", timeout=5)
    except Exception as e:
        print(f"Wipe failed or timeout (expected if it exits): {e}")

    print("Waiting for Proxy to restart...")
    ready = False
    for _ in range(30):
        try:
            # When it restarts, without config it will return 401 on / with basic auth prompt
            r = requests.get("http://localhost:3000/", auth=("setup", "1-mcp-server"), timeout=2)
            if r.status_code == 200:
                ready = True
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    
    if ready:
        print("Reset successful!")
    else:
        print("Reset failed: proxy never came back.")

reset_state()
