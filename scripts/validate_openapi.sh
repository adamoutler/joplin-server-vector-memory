#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

if [ ! -f "server/venv/bin/activate" ]; then
  echo "server/venv not found. Skipping Spectral (requires server env)."
  exit 0
fi

source server/venv/bin/activate

# Dump the OpenAPI spec from the FastAPI app
python -c "
import json
import sys
import os
sys.path.insert(0, os.path.abspath('server'))
from src.main import app

# If app is wrapped in ForceAcceptJSONMiddleware, unwrap it
fastapi_app = getattr(app, 'app', app)

with open('openapi.json', 'w') as f:
    json.dump(fastapi_app.openapi(), f)
"

if [ $? -ne 0 ]; then
  echo "Failed to dump OpenAPI schema."
  exit 1
fi

# Run Spectral linting
echo "Running Spectral linting on generated OpenAPI schema..."
npx --yes @stoplight/spectral-cli lint openapi.json

# Capture the exit code
EXIT_CODE=$?

# Clean up
rm -f openapi.json

if [ $EXIT_CODE -ne 0 ]; then
  echo "Spectral linting failed!"
  exit $EXIT_CODE
fi

exit 0
