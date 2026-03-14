import pytest
import requests
import subprocess
import time
import os

DOCKER_COMPOSE_TEST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docker-compose.test.yml"))
DOCKER_COMPOSE_APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml"))

@pytest.fixture(scope="module", autouse=True)
def live_environment():
    # Start the application
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_APP, "up", "-d", "--build"], check=True)
    
    # Wait for the servers to start
    time.sleep(10)
    
    yield
    
    # Tear down
    subprocess.run(["docker", "compose", "-f", DOCKER_COMPOSE_APP, "down"], check=False)

@pytest.mark.enable_socket
def test_api_server_live_endpoints():
    # Verify that the ports are responding properly
    docs_8000 = requests.get("http://localhost:8000/docs")
    assert docs_8000.status_code == 200, "Port 8000 /docs should return 200"

    docs_3000 = requests.get("http://localhost:3000/docs")
    assert docs_3000.status_code == 200, "Port 3000 /docs should return 200"
    
    # Check /http-api/search without token returns 401
    search_3000 = requests.post("http://localhost:3000/http-api/search", json={"query": "test"})
    assert search_3000.status_code == 401, "Port 3000 /http-api/search should return 401 without auth"
    
    search_8000 = requests.post("http://localhost:8000/http-api/search", json={"query": "test"})
    assert search_8000.status_code == 401, "Port 8000 /http-api/search should return 401 without auth"

if __name__ == "__main__":
    test_api_server_live_endpoints()
    print("All live API endpoint tests passed!")