import os
import subprocess
import yaml

def test_docker_compose_ports_parameterized():
    # Test that docker-compose.yml has parameterized ports
    with open("docker-compose.yml", "r") as f:
        compose_content = yaml.safe_load(f)

    # Check client service ports
    client_ports = compose_content.get("services", {}).get("client", {}).get("ports", [])
    assert any("${FRONTEND_PORT" in port for port in client_ports), "FRONTEND_PORT not parameterized in client service"

    # Check server service ports
    server_ports = compose_content.get("services", {}).get("server", {}).get("ports", [])
    assert any("${BACKEND_PORT" in port for port in server_ports), "BACKEND_PORT not parameterized in server service"

def test_docker_compose_config_with_env():
    # Test that running docker compose config with specific env vars correctly assigns ports
    env = os.environ.copy()
    env["FRONTEND_PORT"] = "3333"
    env["BACKEND_PORT"] = "8888"

    result = subprocess.run(
        ["docker", "compose", "config"],
        env=env,
        capture_output=True,
        text=True,
        check=True
    )

    parsed_config = yaml.safe_load(result.stdout)
    
    # Check client port parsing
    client_ports = parsed_config.get("services", {}).get("client", {}).get("ports", [])
    assert any(str(port.get("published", "")) == "3333" for port in client_ports), "FRONTEND_PORT not correctly interpreted by docker compose"

    # Check server port parsing
    server_ports = parsed_config.get("services", {}).get("server", {}).get("ports", [])
    assert any(str(port.get("published", "")) == "8888" for port in server_ports), "BACKEND_PORT not correctly interpreted by docker compose"
