import requests
import subprocess
import time
import os

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'docker-compose.test.yml'))

def setup():
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)
    
    env["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    env["JOPLIN_ADMIN_PASSWORD"] = "admin"
    env["JOPLIN_BASE_URL"] = "http://joplin:22300"
    
    print("Starting cluster...")
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build", "--wait"], env=env, check=True)

def reset():
    print("Truncating DB...")
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "exec", "-T", "db", "psql", "-U", "joplin", "-d", "joplin", "-c", "TRUNCATE TABLE items, user_items, item_resources, changes, notifications, shares, share_users CASCADE;"], check=True)
    
    print("Wiping auth...")
    try:
        requests.post("http://localhost:3001/auth/wipe", timeout=5)
    except Exception:
        pass
        
    print("Restarting app...")
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "-f", DOCKER_COMPOSE_FILE, "restart", "app"])
    
    print("Waiting for app...")
    ready = False
    for i in range(60):
        try:
            r = requests.get("http://localhost:3001/", auth=("setup", "1-mcp-server"), timeout=2)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)
        print(f"wait {i}")
    
    if not ready:
        print("Failed. Logs:")
        subprocess.run(["docker", "logs", "joplin-test-env-app-1"])

setup()
reset()
