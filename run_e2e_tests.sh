#!/bin/bash
set -e

mkdir -p docs/qa

echo "Running E2E tests with socket enabled..." | tee docs/qa/test-results.latest.txt
source server/venv/bin/activate
pytest tests/test_ephemeral_joplin.py tests/test_e2e_workflow.py server/tests/ | tee -a docs/qa/test-results.latest.txt
