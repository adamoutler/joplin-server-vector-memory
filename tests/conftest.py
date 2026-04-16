import subprocess
import requests
import time
import pytest
from pathlib import Path
import os
import shutil
import pytest_playwright_visual.plugin

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


DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.test.yml'))


@pytest.fixture(autouse=True)
def reset_docker_state():
    """
    Function-scoped fixture to wipe the app state and Joplin database before each test.
    """
    # 1. Truncate Postgres tables to clear Joplin Server data
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "exec", "-T", "db", "psql", "-U", "joplin", "-d", "joplin", "-c", "TRUNCATE TABLE items, user_items, item_resources, changes, notifications, shares, share_users CASCADE;"], check=True)

    # 2. Call /auth/wipe on the Proxy to clear config and memory (must use admin auth since it might be configured)
    try:
        # Try wiping as admin first, then as setup if it was never configured
        r = requests.post("http://localhost:3001/auth/wipe", auth=("admin@localhost", "admin"), timeout=5)
        if r.status_code == 401:
            requests.post("http://localhost:3001/auth/wipe", auth=("setup", "1-mcp-server"), timeout=5)
    except Exception:
        pass

    # We must wait for the container to fully reboot and become responsive
    max_retries = 30
    for _ in range(max_retries):
        try:
            r = requests.get("http://localhost:3001/status", timeout=2)
            if r.status_code in [200, 401]:
                break
        except Exception:
            pass
        time.sleep(1)
