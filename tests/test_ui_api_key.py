import pytest
from playwright.sync_api import sync_playwright, expect
import os
import subprocess
import time
import requests

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.auth.yml'))

@pytest.fixture(scope="module")
def setup_ui_server():
    # Down first
    subprocess.run(["docker", "compose", "-p", "joplin-test-ui", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
    
    # Run container WITHOUT env vars
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)

    subprocess.run(["docker", "compose", "-p", "joplin-test-ui", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build", "--wait"], env=env, check=True)
    
    yield "http://localhost:3002"
    
    subprocess.run(["docker", "compose", "-p", "joplin-test-ui", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])

def test_ui_create_api_key(setup_ui_server, assert_snapshot):
    base_url = setup_ui_server
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Using the setup credentials to login first
        context = browser.new_context(
            http_credentials={'username': 'setup', 'password': '1-mcp-server'}
        )
        page = context.new_page()
        page.goto(base_url)
        
        # Verify we are on the setup page
        expect(page.locator("text=Joplin Memory Server Dashboard").first).to_be_visible()
        
        # Take a visual baseline of the initial dashboard
        assert_snapshot(page.screenshot(), name="dashboard-initial.png")
        
        # We can just test API key creation right here in the setup mode
        # Wait for the API keys section to load
        page.wait_for_selector("#new-key-annotation", state="attached", timeout=10000)
        
        # Fill in key details
        page.fill("#new-key-annotation", "Test Playwright Key")
        
        # Click Create Key
        page.click("button:has-text('Create Key')")
        
        # Wait for success message
        success_msg = page.locator("#keys-msg")
        expect(success_msg).to_have_text("Key created successfully.", timeout=5000)
        
        # Take a visual baseline after key creation
        assert_snapshot(page.locator("#api-keys-list").screenshot(mask=[page.locator("#api-keys-list input")]), name="dashboard-with-key.png")
        
        # Verify the key appears in the list
        expect(page.locator("#api-keys-list div:has-text('Test Playwright Key')").first).to_be_visible()
        
        browser.close()
