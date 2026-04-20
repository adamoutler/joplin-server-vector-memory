import os
import subprocess
import yaml


def test_docker_compose_ports_parameterized(ephemeral_joplin):
    # Test that docker-compose.yml has parameterized ports
    with open("docker-compose.yml", "r") as f:
        compose_content = yaml.safe_load(f)

    # Check app service ports
    app_ports = compose_content.get("services", {}).get("app", {}).get("ports", [])
    assert any("${FRONTEND_PORT" in port for port in app_ports), "FRONTEND_PORT not parameterized in app service"
    assert any("${BACKEND_PORT" in port for port in app_ports), "BACKEND_PORT not parameterized in app service"


def test_docker_compose_config_with_env(ephemeral_joplin):
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

    # Check app port parsing
    app_ports = parsed_config.get("services", {}).get("app", {}).get("ports", [])
    assert any(str(port.get("published", "")) == "3333" for port in app_ports), "FRONTEND_PORT not correctly interpreted by docker compose"
    assert any(str(port.get("published", "")) == "8888" for port in app_ports), "BACKEND_PORT not correctly interpreted by docker compose"
