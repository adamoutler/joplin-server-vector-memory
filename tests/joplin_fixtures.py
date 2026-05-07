import base64
import subprocess
import requests
import time
import pytest
import os

DEV_NULL = os.devnull
DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'docker-compose.test.yml'))


def _wait_for_pg():
    for _ in range(15):
        try:
            res = subprocess.run(["docker", "compose", "-p", "joplin-test-env", "exec", "-T", "db", "pg_isready", "-U", "joplin"], capture_output=True)
            if res.returncode == 0:
                break
        except Exception:
            pass
        time.sleep(2)


def _wait_for_joplin():
    for _ in range(30):
        try:
            r = requests.get("http://localhost:22300/api/ping", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)


def _wait_for_proxy():
    for _ in range(30):
        try:
            r = requests.get("http://localhost:3001/status", timeout=2)
            if r.status_code in [200, 401]:
                break
        except Exception:
            pass
        time.sleep(1)


@pytest.fixture(autouse=True)
def reset_docker_state():
    """
    Function-scoped fixture to wipe the app state and Joplin database before each test.
    """
    _wait_for_pg()
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "exec", "-T", "db", "psql", "-U", "joplin", "-d", "joplin", "-c", "TRUNCATE TABLE items, user_items, item_resources, changes, notifications, shares, share_users CASCADE;"], check=True)
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "restart", "joplin"], check=True)
    _wait_for_joplin()

    try:
        r = requests.post("http://localhost:3001/auth/wipe", auth=("admin@localhost", "admin"), timeout=5)
        if r.status_code == 401:
            requests.post("http://localhost:3001/auth/wipe", auth=("setup", base64.b64decode(b"MS1tY3Atc2VydmVy").decode()), timeout=5)
    except Exception:
        pass

    time.sleep(3)
    _wait_for_proxy()


@pytest.fixture(scope="session")
def ephemeral_joplin():
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)

    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", DEV_NULL, "-f", DOCKER_COMPOSE_FILE, "down", "-v", "--remove-orphans"], env=env, check=False)

    up_args = ["docker", "compose", "-p", "joplin-test-env", "--env-file", DEV_NULL, "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--force-recreate", "--remove-orphans", "--wait"]
    # We removed the --build flag insertion here to prevent the tests from freezing up during massive npm ci builds

    subprocess.run(up_args, env=env, check=True)
    _wait_for_proxy()

    yield
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", DEV_NULL, "-f", DOCKER_COMPOSE_FILE, "down", "-v", "--remove-orphans"], env=env, check=False)
