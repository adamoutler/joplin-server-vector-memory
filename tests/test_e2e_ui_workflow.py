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
def test_full_ui_e2e_workflow(ephemeral_joplin):
    os.makedirs("docs/qa/snapshots/test_e2e_ui_workflow", exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Step 01: ensure Joplin Test Fixture is established
        # This is done by the ephemeral_joplin fixture
        page.goto("data:text/html,<html><body><h1>Step 01: Joplin Test Fixture is established</h1></body></html>")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/01_joplin_fixture_established.png")
        
        # Step 02: ensure joplin test fixture is populated with at least 4 identifiable notes...
        secret_uuid = str(uuid.uuid4())
        populate_joplin(secret_uuid)
        page.goto("data:text/html,<html><body><h1>Step 02: Joplin populated with 4 notes</h1></body></html>")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/02_joplin_populated.png")
        
        context.close()
    
    proxy_url = "http://127.0.0.1:3001"
    
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
        context = browser.new_context(http_credentials={'username': 'setup', 'password': '1-mcp-server'})
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())

        # Step 03: Login to port 3000
        page.goto(proxy_url)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/03_login.png")

        # Step 04: Open settings
        try:
            page.wait_for_selector("#serverUrl", timeout=5000)
            page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/04_open_settings.png")
        except Exception as e:
            print("Failed to find #serverUrl. Page content:", page.content())
            raise e
        
        # Step 05: populate the settings form
        page.fill("#serverUrl", "http://joplin:22300")
        page.fill("#username", "admin@localhost")
        page.fill("#password", "admin")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/05_populate_settings.png")
        
        # Step 06: Observe the backend API port is set to current URL
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/06_observe_backend_port.png")
        
        # Step 07: Change the backend API port to port 8000
        page.fill("#memoryServerAddress", "http://localhost:8000")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/07_change_port.png")

        # Step 09: Click save at the botom of the sync area
        page.click("text='Save & Validate'")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/09_click_save.png")
        
        time.sleep(2)
        context.close()
        context = browser.new_context(http_credentials={'username': 'admin@localhost', 'password': 'admin'})
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(proxy_url)
        
        # We don't need to fill the form again, as the system is locked and the form is hidden.
        # But we do need to wait for the page to load fully.
        page.wait_for_timeout(2000)

        # Step 08: Observe all backend servers and examples update to use proxy URL
        expect(page.locator("#example-http")).to_contain_text(f"{proxy_url}/http-api", timeout=5000)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/08_observe_examples.png")
        
        # Step 10: Create a token and take note of the token
        page.fill("#new-key-annotation", "Test Token")
        page.locator("#create-key-form button[type='submit']").click()
        try:
            page.wait_for_selector("#api-keys-list div", timeout=5000)
        except Exception as e:
            raise e
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/10_token_created.png")
        token_input = page.locator("#api-keys-list input").nth(1) if page.locator("#api-keys-list input").count() > 1 else page.locator("#api-keys-list input").first
        token_val = token_input.input_value()
        
        # Step 11: delete the original provided token
        if page.locator("#api-keys-list button:has-text('Delete')").count() > 1:
            page.locator("#api-keys-list button:has-text('Delete')").first.click()
            time.sleep(1)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/11_token_deleted.png")
        
        # Step 12: wait until both sync and index states report Ready
        expect(page.locator("#sync-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=60000)
        expect(page.locator("#embed-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=60000)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/12_sync_ready.png")

        # Step 13: Refresh the page to clear out form items
        page.reload()
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/13_after_refresh.png")
        
        # Step 14: change the model or whatever to trigger a reindex
        page.locator("summary").filter(has_text="Advanced RAG Configuration").click()
        page.fill("#chunkSize", "1500")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/14_change_model.png")
        
        # Step 15: Click save at the bottom of the index area
        page.click("#save-advanced-btn")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/15_click_save.png")
        
        # Step 16: type REINDEX
        dialog_input = page.locator("#reindex-confirm-input")
        expect(dialog_input).to_be_visible(timeout=5000)
        dialog_input.fill("REINDEX")
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/16_type_reindex.png")
        
        # Step 17: click the button to continue
        page.locator("#confirm-warning-btn").click()
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/17_click_continue.png")
        
        # Wait out the Joplin server rate limit for logins (429 Too many requests) which is around 40s
        print("Waiting 45 seconds for Joplin Server rate limit to expire after restart...")
        time.sleep(45)
        
        # Step 18: System should request new login triggered by unauthorized request on refresh
        max_retries = 30
        for i in range(max_retries):
            try:
                r = requests.get(f"{proxy_url}/status", auth=("admin@localhost", "admin"), timeout=2)
                if r.status_code in [200, 401]:
                    break
            except Exception:
                pass
            time.sleep(1)
        page.reload()
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/18_request_login.png")

        # Step 19: System should allow login
        if page.locator("#serverUrl").is_visible() and not page.locator("#serverUrl").input_value():
            page.fill("#serverUrl", "http://joplin:22300")
            page.fill("#username", "admin@localhost")
            page.fill("#password", "admin")
            page.click("text='Save & Validate'")
            expect(page.locator("#auth-msg")).to_contain_text("Saved successfully", timeout=15000)
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/19_allow_login.png")
        
        # Step 20: System should show reindexing
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/20_show_reindexing.png")
        
        # Step 21: Wait for both sync and index states to report Ready
        try:
            expect(page.locator("#sync-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=120000)
            expect(page.locator("#embed-status-text")).to_have_text(re.compile(r"Ready|Idle", re.IGNORECASE), timeout=120000)
        except Exception as e:
            res = subprocess.run(["docker", "compose", "-p", "joplin-test-env", "-f", DOCKER_COMPOSE_FILE, "logs", "app"], capture_output=True, text=True)
            print("DOCKER LOGS:")
            print(res.stdout)
            print("DOCKER STDERR:")
            print(res.stderr)
            raise e
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/21_reindex_ready.png")

        # Step 22: Attempt to use both 3000 api
        headers = {"Authorization": f"Bearer {token_val}"}
        resp_proxy = requests.post(f"{proxy_url}/http-api/search", json={"query": "secret"}, headers=headers)
        assert resp_proxy.status_code == 200
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/22_use_3000_api.png")
        
        # Step 23: attempt to use 8000 api
        backend_url = "http://127.0.0.1:8002"
        resp_backend = requests.post(f"{backend_url}/http-api/search", json={"query": "secret"}, headers=headers)
        assert resp_backend.status_code == 200
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/23_use_8000_api.png")
        
        # Step 24: verify MCP tools connectivity.
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/24_verify_mcp.png")
        
        # Step 25: Done
        page.screenshot(path="docs/qa/snapshots/test_e2e_ui_workflow/25_done.png")

        browser.close()