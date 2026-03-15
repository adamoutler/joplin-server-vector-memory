import subprocess
import time
import requests
import os
import json

def run():
    DOCKER_COMPOSE_TEST = os.path.abspath("docker-compose.test.yml")
    DOCKER_COMPOSE_APP = os.path.abspath("docker-compose.yml")
    
    # 1. Start Joplin from test compose
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_TEST, "up", "-d", "joplin"], check=True)
    
    # Wait for joplin
    for _ in range(30):
        try:
            if requests.get("http://localhost:22300/api/ping").status_code == 200:
                print("Joplin is up")
                break
        except:
            pass
        time.sleep(1)
        
    # 2. Start App from app compose
    env = os.environ.copy()
    env["JOPLIN_SERVER_URL"] = "http://localhost:22300"
    env["JOPLIN_USERNAME"] = "admin@localhost"
    env["JOPLIN_PASSWORD"] = "admin"
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_APP, "up", "-d", "--build"], env=env, check=True)
    
    time.sleep(10)
    
    # 3. Get token
    result = subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_APP, "exec", "app", "cat", "/app/data/config.json"], capture_output=True, text=True)
    print("Config.json output:", result.stdout)
    if result.stdout.strip():
        config = json.loads(result.stdout)
        token = config.get("token")
        print("Token:", token)
        
        # Test Search with Token
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.post("http://localhost:3000/http-api/search", json={"query": "test"}, headers=headers)
        print("Search 3000 status:", res.status_code)
        res = requests.post("http://localhost:8000/http-api/search", json={"query": "test"}, headers=headers)
        print("Search 8000 status:", res.status_code)
        
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_APP, "down"])
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_TEST, "down"])

if __name__ == "__main__":
    run()
