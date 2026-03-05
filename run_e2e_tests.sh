#!/bin/bash
set -e

echo "Running E2E tests with socket enabled..."
source server/venv/bin/activate
pytest --force-enable-socket tests/test_ephemeral_joplin.py tests/test_e2e_workflow.py server/tests/
