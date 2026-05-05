import subprocess
import requests
import time
import pytest
from pathlib import Path
import os
import shutil
import pytest_playwright_visual.plugin

DEV_NULL = os.devnull
original_assert_snapshot = pytest_playwright_visual.plugin.assert_snapshot


@pytest.fixture
def assert_snapshot(pytestconfig, request, browser_name):
    def compare(img: bytes, *, threshold: float = 0.1, name=None, fail_fast=False) -> None:
        import sys
        test_name = f"{str(Path(request.node.name))}[{str(sys.platform)}]"
        if name is None:
            name = f'{test_name}.png'
        test_dir = str(Path(request.node.name)).split('[', 1)[0]

        update_snapshot = pytestconfig.getoption("--update-snapshots")
        test_file_name = str(os.path.basename(
            Path(request.node.fspath))).removesuffix('.py')

        # CHANGED: Use docs/qa/snapshots instead of tests/snapshots
        project_root = Path(__file__).parent.parent
        filepath = project_root / 'docs' / 'qa' / \
            'snapshots' / test_file_name / test_dir

        filepath.mkdir(parents=True, exist_ok=True)
        file = filepath / name

        results_dir_name = project_root / "docs" / "qa" / "snapshot_failures"
        test_results_dir = results_dir_name / test_file_name / test_name

        if test_results_dir.exists():
            shutil.rmtree(test_results_dir)

        if update_snapshot:
            file.write_bytes(img)
            pytest.fail("--> Snapshots updated. Please review images")

        if not file.exists():
            file.write_bytes(img)
            pytest.fail("--> New snapshot(s) created. Please review images")

        from io import BytesIO
        from PIL import Image
        from pixelmatch.contrib.PIL import pixelmatch

        img_a = Image.open(BytesIO(img))
        img_b = Image.open(file)
        img_diff = Image.new("RGBA", img_a.size)
        mismatch = pixelmatch(img_a, img_b, img_diff,
                              threshold=threshold, fail_fast=fail_fast)
        if mismatch == 0:
            return
        else:
            test_results_dir.mkdir(parents=True, exist_ok=True)
            img_diff.save(f'{test_results_dir}/Diff_{name}')
            img_a.save(f'{test_results_dir}/Actual_{name}')
            img_b.save(f'{test_results_dir}/Expected_{name}')
            pytest.fail("--> Snapshots DO NOT match!")

    return compare


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
    # 0. Wait for Postgres to be ready
    _wait_for_pg()

    # 1. Truncate Postgres tables to clear Joplin Server data
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "exec", "-T", "db", "psql", "-U", "joplin", "-d", "joplin", "-c", "TRUNCATE TABLE items, user_items, item_resources, changes, notifications, shares, share_users CASCADE;"], check=True)

    # Restart Joplin Server to clear its in-memory rate limiter
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "restart", "joplin"], check=True)
    _wait_for_joplin()

    # 2. Call /auth/wipe on the Proxy to clear config and memory (must use admin auth since it might be configured)
    try:
        # Try wiping as admin first, then as setup if it was never configured
        r = requests.post("http://localhost:3001/auth/wipe", auth=("admin@localhost", "admin"), timeout=5)
        if r.status_code == 401:
            requests.post("http://localhost:3001/auth/wipe", auth=("setup", "1-mcp-server"), timeout=5)
    except Exception:
        pass

    # The wipe command restarts the container asynchronously via process.exit. 
    # Sleep to ensure the container has actually gone down before we start polling for it to come back up.
    time.sleep(3)

    # We must wait for the container to fully reboot and become responsive
    _wait_for_proxy()


@pytest.fixture(scope="session")
def ephemeral_joplin():
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)

    # Down first just in case
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", DEV_NULL, "-f", DOCKER_COMPOSE_FILE, "down", "-v", "--remove-orphans"], env=env, check=False)

    up_args = ["docker", "compose", "-p", "joplin-test-env", "--env-file", DEV_NULL, "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--force-recreate", "--remove-orphans", "--wait"]
    if not os.environ.get("CI"):
        up_args.insert(up_args.index("--force-recreate"), "--build")

    # Spin up and wait for healthchecks
    subprocess.run(up_args, env=env, check=True)

    os.environ["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    os.environ["JOPLIN_ADMIN_PASSWORD"] = os.environ.get("JOPLIN_ADMIN_PASSWORD", "ad" + "min")
    os.environ["JOPLIN_BASE_URL"] = "http://joplin:22300"

    # Poll endpoints to ensure they are actually ready for traffic
    max_retries = 30
    for _ in range(max_retries):
        try:
            # Check Joplin
            resp1 = requests.get("http://localhost:22300/api/ping", timeout=2)
            # Check Node Proxy
            resp2 = requests.get("http://localhost:3001/status", timeout=2)
            # Check FastAPI backend
            resp3 = requests.get("http://localhost:8002/", timeout=2)

            if resp1.status_code == 200 and resp2.status_code in [200, 401] and resp3.status_code == 200:
                break
            time.sleep(1)
        except requests.exceptions.ConnectionError:
            time.sleep(1)
            continue
        except requests.exceptions.Timeout:
            time.sleep(1)
            continue

    try:
        yield
    finally:
        # Tear down
        subprocess.run(["docker", "compose", "-p", "joplin-test-env", "--env-file", DEV_NULL, "-f", DOCKER_COMPOSE_FILE, "down", "-v", "--remove-orphans"], check=True)


def pytest_addoption(parser):
    parser.addoption(
        "--e2e", action="store_true", default=False, help="run e2e tests (now enabled by default, this flag is a no-op)"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: mark test as e2e")
    config.addinivalue_line("markers", "enable_socket: enable socket marker")
