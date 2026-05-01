#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

if [ ! -f "server/venv/bin/activate" ]; then
  echo "server/venv not found. Please install the server environment."
  exit 1
fi

source server/venv/bin/activate
python scripts/validate_mcp.py
