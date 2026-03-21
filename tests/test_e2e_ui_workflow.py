import pytest
from playwright.sync_api import sync_playwright, expect
import os
import subprocess
import time
import requests
import sys
import uuid
import re

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.test.yml'))

def populate_joplin(secret_uuid):
    # Create notes via the Node.js test script to populate the ephemeral Joplin instance
    client_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'client'))
    result = subprocess.run(
        ["docker", "compose", "-p", "joplin-test-env", "-f", DOCKER_COMPOSE_FILE, "exec", "-T",
         "-e", "OLLAMA_URL=http://ollama:11434",
         "-e", "JOPLIN_SERVER_URL=http://joplin:22300",
         "-e", "JOPLIN_USERNAME=admin@localhost",
         "-e", "JOPLIN_PASSWORD=admin",
         "app", "node", "client/e2e_create_sync.js", secret_uuid],
        cwd=os.path.dirname(DOCKER_COMPOSE_FILE),
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Failed to populate Joplin: {result.stderr}"


@pytest.mark.enable_socket
def test_full_ui_e2e_workflow():
    # secret_uuid = str(uuid.uuid4())
    # populate_joplin(secret_uuid)
    
    proxy_url = "http://127.0.0.1:3001"
    os.makedirs("docs/qa/snapshots/test_e2e_ui_workflow", exist_ok=True)
    
    # Wait for the frontend to be available
    max_retries = 30
    for i in range(max_retries):
        try:
            r = requests.get(f"{proxy_url}/")
            if r.status_code in [200, 401]:
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
            pass
        time.sleep(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Initial login with setup credentials
        context = browser.new_context(http_credentials={'username': 'setup', 'password': '1-mcp-server'})
        page = context.new_page()

        # Handle any alerts (like the requireRelogin one)
        page.on("dialog", lambda dialog: dialog.accept())

        # Step 3: Login to port 3000 (mapped to 3001 in our tests)
        page.goto(proxy_url)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/01_initial_load.png")

        try:
            # Step 4 & 5: Open settings and populate the settings form
            page.fill("#serverUrl", "http://joplin:22300")
        except Exception as e:
            print("Failed to find #serverUrl. Page content:")
            print(page.content())
            raise e
        
        page.fill("#username", "admin@localhost")
        page.fill("#password", "admin")
        
        # Step 6 & 7: Change backend API port to port 8000
        page.fill("#memoryServerAddress", "http://localhost:8000")

        # Step 9: Click save at the bottom of the sync area
        # This will trigger an alert and a reload because of isMarriage
        page.click("text='Save & Validate'")
        
        # Wait for the reload to trigger an auth failure because the context still uses setup:1-mcp-server
        # We need to create a new context with the correct credentials.
        time.sleep(2)
        
        context.close()
        context = browser.new_context(http_credentials={'username': 'admin@localhost', 'password': 'admin'})
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(proxy_url)
        
        # Now we need to save the configuration again, or is it already saved? The config is written, 
        # but the node server might not have started the sync loop yet if we need to enter credentials again?
        # Actually, in isMarriage, it returns before startSync, so we must save again.
        page.fill("#serverUrl", "http://joplin:22300")
        page.fill("#username", "admin@localhost")
        page.fill("#password", "admin")
        page.fill("#memoryServerAddress", "http://localhost:8000")
        page.click("text='Save & Validate'")
        
        # Wait for validation message
        expect(page.locator("#auth-msg")).to_contain_text("Saved successfully", timeout=15000)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/02_auth_saved.png")
        
        # Now that credentials are saved, basic auth changes to the user's joplin credentials.
        # We need to create a new context with the new credentials for subsequent requests if it forces a reload,
        # but the frontend uses the same page until we refresh.
        
        # Step 8: Observe all backend servers and examples update to use proxy URL
        expect(page.locator("#example-http")).to_contain_text(f"{proxy_url}/http-api", timeout=5000)
        
        # Step 10: Create a token and take note of the token
        page.fill("#new-key-annotation", "Test Token")
        page.locator("#create-key-form button[type='submit']").click()
        
        try:
            # We wait for at least one token to appear (could be default + newly created)
            page.wait_for_selector("#api-keys-list div", timeout=5000)
        except Exception as e:
            print("Failed to find token group. Keys Msg:", page.locator("#keys-msg").inner_text())
            print("Page content:", page.content())
            raise e
            
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/03_token_created.png")
        
        # Grab token (simulate taking note)
        token_input = page.locator("#api-keys-list input").first
        token_val = token_input.input_value()
        assert len(token_val) > 10
        
        # Step 12: Wait until both sync and index states report Ready
        expect(page.locator("#sync-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=60000)
        expect(page.locator("#embed-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=60000)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/04_sync_ready.png")

        # Step 13: Refresh the page - now requires new auth!
        context.close()
        context = browser.new_context(http_credentials={'username': 'admin@localhost', 'password': 'admin'})
        page = context.new_page()
        page.goto(proxy_url)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/05_after_refresh.png")
        
        # Step 14 & 15: change the model to trigger a reindex
        page.locator("summary").filter(has_text="Advanced RAG Configuration").click()
        page.fill("#chunkSize", "1500")
        
        page.click("#save-advanced-btn")
        
        # Step 16 & 17: type REINDEX and click to continue
        dialog_input = page.locator("#reindex-confirm-input")
        expect(dialog_input).to_be_visible(timeout=5000)
        dialog_input.fill("REINDEX")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/06_reindex_dialog.png")
        
        page.locator("#confirm-warning-btn").click()
        
        # Wait for the reindex to start and the container to restart
        print("Waiting for container to restart after Wipe & Apply...")
        time.sleep(5)
        
        max_retries = 30
        for i in range(max_retries):
            try:
                r = requests.get(f"{proxy_url}/status", auth=("admin@localhost", "admin"), timeout=2)
                if r.status_code in [200, 401]:
                    break
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError):
                pass
            time.sleep(1)
            
        print("Container restarted. Reloading UI...")
        page.reload()
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/06_reindexing_started.png")

        # Re-authenticate if requested (step 19)
        if page.locator("#serverUrl").is_visible() and not page.locator("#serverUrl").input_value():
            page.fill("#serverUrl", "http://joplin:22300")
            page.fill("#username", "admin@localhost")
            page.fill("#password", "admin")
            page.click("text='Save & Validate'")
            expect(page.locator("#auth-msg")).to_contain_text("Saved successfully", timeout=15000)
        
        # Step 21: Wait for both sync and index states to report Ready again
        try:
            expect(page.locator("#sync-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=60000)
            expect(page.locator("#embed-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=60000)
        except Exception as e:
            print("Sync failed! Sync status:", page.locator("#sync-status-text").inner_text())
            print("Sync progress detail:", page.locator("#sync-prog").inner_text())
            raise e
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/08_reindex_ready.png")

        # Step 22: Attempt to use 3000 api (Proxy HTTP search)
        headers = {"Authorization": f"Bearer {token_val}"}
        resp_proxy = requests.post(f"{proxy_url}/http-api/search", json={"query": "secret"}, headers=headers)
        assert resp_proxy.status_code == 200, f"Proxy API failed with {resp_proxy.status_code}: {resp_proxy.text}"
        
        # Step 23: Attempt to use 8000 api (Backend HTTP search)
        backend_url = "http://127.0.0.1:8002"
        resp_backend = requests.post(f"{backend_url}/http-api/search", json={"query": "secret"}, headers=headers)
        assert resp_backend.status_code == 200, f"Backend API failed with {resp_backend.status_code}: {resp_backend.text}"

        browser.close()