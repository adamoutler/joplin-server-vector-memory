#!/bin/bash
set -e

mkdir -p docs/qa

echo "Running E2E tests with socket enabled..." | tee docs/qa/test-results.latest.txt
source server/venv/bin/activate
playwright install chromium
pytest --timeout=600 tests/test_ephemeral_joplin.py tests/test_operational_system.py tests/test_e2e_workflow.py server/tests/ | tee -a docs/qa/test-results.latest.txt

echo "Tearing down main test environment to free resources..." | tee -a docs/qa/test-results.latest.txt
docker compose -p joplin-test-env -f docker-compose.test.yml down -v

echo "Running Live API E2E tests..." | tee -a docs/qa/test-results.latest.txt
pytest --timeout=600 tests/test_live_api_e2e.py | tee -a docs/qa/test-results.latest.txt

echo "Running Auth Flow tests..." | tee -a docs/qa/test-results.latest.txt
pytest --timeout=600 tests/test_auth_flow.py | tee -a docs/qa/test-results.latest.txt

echo "Running UI Tests..." | tee -a docs/qa/test-results.latest.txt
pytest --timeout=600 tests/test_ui_api_key.py | tee -a docs/qa/test-results.latest.txt
