import pytest
from playwright.sync_api import sync_playwright, expect
import os
import subprocess
import time
import requests
import sys

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.test.yml'))

@pytest.fixture(scope="module")
def setup_ui_server_advanced():
    print("\n[setup_ui_server_advanced] Tearing down any existing containers...", file=sys.stderr)
    subprocess.run(["docker", "compose", "-p", "joplin-test-adv", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
    
    # Run container WITHOUT env vars to ensure we hit the setup screen
    env = os.environ.copy()
    env.pop("JOPLIN_SERVER_URL", None)
    env.pop("JOPLIN_USERNAME", None)
    env.pop("JOPLIN_PASSWORD", None)
    env.pop("JOPLIN_MASTER_PASSWORD", None)
    
    # Let Joplin know what its url should be so it allows connections
    env["JOPLIN_ADMIN_EMAIL"] = "admin@localhost"
    env["JOPLIN_ADMIN_PASSWORD"] = "admin"
    env["JOPLIN_BASE_URL"] = "http://joplin:22300"

    print("[setup_ui_server_advanced] Starting joplin-test-adv cluster...", file=sys.stderr)
    subprocess.run(["docker", "compose", "-p", "joplin-test-adv", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "up", "-d", "--build"], env=env, check=True)
    
    # Wait for the app container to be ready in setup mode
    ready = False
    for _ in range(60):
        try:
            resp = requests.get("http://localhost:3001/", auth=("setup", "1-mcp-server"), timeout=30)
            if resp.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)

    if not ready:
        subprocess.run(["docker", "compose", "-p", "joplin-test-adv", "-f", DOCKER_COMPOSE_FILE, "logs", "app"])
        subprocess.run(["docker", "compose", "-p", "joplin-test-adv", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])
        pytest.fail("App container did not start in time")
        
    yield "http://localhost:3001"
    
    subprocess.run(["docker", "compose", "-p", "joplin-test-adv", "--env-file", "/dev/null", "-f", DOCKER_COMPOSE_FILE, "down", "-v"])


def test_ui_advanced_settings_flow(setup_ui_server_advanced, assert_snapshot):
    base_url = setup_ui_server_advanced
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Using the setup credentials to login first
        context = browser.new_context(
            http_credentials={'username': 'setup', 'password': '1-mcp-server'}
        )
        page = context.new_page()
        
        # We need to catch dialogs (alerts)
        dialog_messages = []
        page.on("dialog", lambda dialog: (dialog_messages.append(dialog.message), dialog.accept()))
        
        page.goto(base_url)
        expect(page.locator("text=Joplin Memory Server Dashboard").first).to_be_visible()
        
        # 1. Fill out Initial Setup Form
        page.fill("#serverUrl", "http://joplin:22300/")
        page.fill("#username", "admin@localhost")
        page.fill("#password", "admin")
        
        # When saving for the first time, it alerts and reloads the page.
        # We need to catch the alert and accept it, and wait for the reload.
        page.click("button:has-text('Save & Validate')")
        
        # Verify the alert message said to log in again
        # Note: the dialog listener automatically accepts it
        page.wait_for_timeout(2000) # Give it a moment to process the alert and reload
        
        # The page reloads and throws 401 because 'setup' is no longer valid.
        # We must create a new context with the real credentials to continue.
        context.close()
        
        context2 = browser.new_context(
            http_credentials={'username': 'admin@localhost', 'password': 'admin'}
        )
        page2 = context2.new_page()
        
        # We need to catch dialogs on the new page too
        dialog_messages.clear()
        page2.on("dialog", lambda dialog: (dialog_messages.append(dialog.message), dialog.accept()))
        
        page2.goto(base_url)
        expect(page2.locator("text=Joplin Memory Server Dashboard").first).to_be_visible()
        
        # Wait for Joplin server to be fully initialized and for sync to begin
        time.sleep(10)
        
        # 2. Open Advanced RAG Configuration
        page2.click("summary:has-text('Advanced RAG Configuration')")
        
        # Verify the default is "Local CPU Model"
        expect(page2.locator("#embeddingMode")).to_have_value("local")
        
        # 3. Change to Ollama
        page2.select_option("#embeddingMode", "ollama")
        
        # Verify Ollama fields are now visible
        expect(page2.locator("#ollama-fields")).to_be_visible()
        
        # 4. Fill with FAKE model to test the Pre-Flight Probe
        page2.fill("#ollamaBaseUrl", "http://ollama:11434")
        page2.fill("#ollamaModel", "this-is-a-fake-model-that-will-404")
        
        page2.click("button:has-text('Save Advanced Settings')")
        
        # Wait for the button to go to 'Testing Connection...' and come back
        expect(page2.locator("button:has-text('Save Advanced Settings')")).to_be_enabled(timeout=10000)
        
        # Verify the JS alert caught the 400 error
        assert len(dialog_messages) > 0, "Expected a Javascript alert for bad model connection"
        assert "Error:" in dialog_messages[-1] or "Network" in dialog_messages[-1]
        
        # 5. Fill with REAL model
        page2.fill("#ollamaModel", "nomic-embed-text")
        page2.click("button:has-text('Save Advanced Settings')")
        
        # 6. Verify the REINDEX Modal popped up
        expect(page2.locator("dialog")).to_be_visible(timeout=5000)
        expect(page2.locator("dialog h3")).to_contain_text("Critical Changes Detected")
        
        # 7. Attempt to click Confirm without typing REINDEX
        expect(page2.locator("#confirm-warning-btn")).to_be_disabled()
        
        # 8. Type REINDEX
        page2.fill("#reindex-confirm-input", "REINDEX")
        expect(page2.locator("#confirm-warning-btn")).to_be_enabled()
        
        # 9. Click Confirm
        page2.click("#confirm-warning-btn")
        
        # Wait for success message from backend (button text changes)
        expect(page2.locator("#save-advanced-btn")).to_have_text("Saved Successfully!", timeout=10000)
        
        # 10. Verify that the Docker container actually restarted itself as a result of the REINDEX
        # If it restarted, our proxy might drop connection or it will just be down for a second.
        # We will poll /status to see if it comes back online.
        restarted = False
        for _ in range(15):
            try:
                resp = requests.get(f"{base_url}/status", auth=("admin@localhost", "admin"), timeout=2)
                if resp.status_code == 200:
                    restarted = True
                    break
            except Exception:
                pass
            time.sleep(1)
            
        assert restarted, "Server did not come back online after REINDEX reboot trigger."
        
        browser.close()
