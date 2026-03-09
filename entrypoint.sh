#!/bin/bash
set -e

# Start the Python MCP Server in the background
echo "Starting Python Backend (FastMCP)..."
cd /app/server
uvicorn src.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*" &
BACKEND_PID=$!

# Start the Node.js Client Proxy/UI in the foreground
echo "Starting Node.js Proxy and Sync Client..."
cd /app/client
node src/index.js &
CLIENT_PID=$!

# Wait for both processes
wait -n $BACKEND_PID $CLIENT_PID

# If either exits, exit the container
echo "A primary process exited. Shutting down container..."
exit 1